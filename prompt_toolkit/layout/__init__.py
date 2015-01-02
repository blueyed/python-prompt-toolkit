"""
Layout representation.
"""
from __future__ import unicode_literals

from six import add_metaclass
from pygments.token import Token
from abc import ABCMeta, abstractmethod

from ..renderer import Screen, Size, Point, Char
from ..filters import Filter
from ..renderer import WritePosition


__all__ = (
    'Layout',
)


class _SimpleLRUCache(object):
    """
    Very simple LRU cache.

    :param maxsize: Maximum size of the cache. (Don't make it too big.)
    """
    def __init__(self, maxsize=8):
        self.maxsize = maxsize
        self._cache = []  # List of (key, value).

    def get(self, key, getter_func):
        """
        Get object from the cache.
        If not found, call `getter_func` to resolve it, and put that on the top
        of the cache instead.
        """
        # Look in cache first.
        for k, v in self._cache:
            if k == key:
                return v

        # Not found? Get it.
        value = getter_func()
        self._cache.append((key, value))

        if len(self._cache) > self.maxsize:
            self._cache = self._cache[-self.maxsize:]

        return value





class LayoutDimension(object):
    def __init__(self, min=None, max=None):
        self.min = min or 1
        self.max = max or 1000 * 1000

    @classmethod
    def exact(cls, amount):
        return cls(min=amount, max=amount)

    def __repr__(self):
        return 'LayoutDimension(min=%r, max=%r)' % (self.min, self.max)


def _sum_layout_dimensions(dimensions):
    min = sum([d.min for d in dimensions if d.min is not None])
    max = sum([d.max for d in dimensions if d.max is not None])

    return LayoutDimension(min=min, max=max)


def _max_layout_dimensions(dimensions):
    min_ = max([d.min for d in dimensions if d.min is not None])
    max_ = max([d.max for d in dimensions if d.max is not None])

    return LayoutDimension(min=min_, max=max_)


class Layout(object):
    """
    Base class for user interface layout.
    """
    @abstractmethod
    def reset(self):
        pass

    @abstractmethod
    def width(self, cli):
        # Should return a LayoutDimension
        pass

    @abstractmethod
    def height(self, cli, width):  # XXX: we should be able to calculate the height, given the current width.
        # Should return a LayoutDimension
        pass

    @abstractmethod
    def write_to_screen(self, cli, screen, write_position):
        pass

Layout = add_metaclass(ABCMeta)(Layout)


class HSplit(Layout):
    """
    Several layouts, one stacked above/under the other.
    """
    def __init__(self, children):
        assert all(isinstance(c, Layout) for c in children)
        self.children = children

    def height(self, cli):
        dimensions = [c.height(cli) for c in self.children]
        return _sum_layout_dimensions(dimensions)

    def width(self, cli):
        dimensions = [c.width(cli) for c in self.children]
        return _max_layout_dimensions(dimensions)

    def reset(self):
        for c in self.children:
            c.reset()

    def write_to_screen(self, cli, screen, write_position):
        """
        Render the prompt to a `Screen` instance.

        :param screen: The :class:`Screen` class into which we write the output.
        """
        # Calculate heights.
        dimensions = [c.height(cli) for c in self.children]
        sum_dimensions = _sum_layout_dimensions(dimensions)

        # If there is not enough space for both.
        # Don't do anything. (TODO: show window to small message.)
        if sum_dimensions.min > write_position.max_height:
            return

        # Find optimal sizes. (Start with minimal size, increase until we cover
        # the whole height.)
        sizes = [d.min for d in dimensions]
        i = 0
        while sum(sizes) < min(write_position.min_height, sum_dimensions.max):
            if sizes[i] < dimensions[i].max:
                sizes[i] += 1
            i = (i + 1) % len(sizes)

        # Draw child panes.
        ypos = write_position.ypos
        xpos = write_position.xpos
        width = write_position.width

        for s, c in zip(sizes, self.children):
            c.write_to_screen(cli, screen, WritePosition(xpos, ypos, width, s))
            ypos += s


class VSplit(Layout):
    """
    Several layouts, one stacked left/right of the other.
    """
    def __init__(self, children):
        assert all(isinstance(c, Layout) for c in children)
        self.children = children

    def height(self, cli):
        dimensions = [c.height(cli) for c in self.children]
        return _max_layout_dimensions(dimensions)

    def width(self, cli):
        dimensions = [c.width(cli) for c in self.children]
        return _sum_layout_dimensions(dimensions)

    def reset(self):
        for c in self.children:
            c.reset()

    def write_to_screen(self, cli, screen, write_position):
        """
        Render the prompt to a `Screen` instance.

        :param screen: The :class:`Screen` class into which we write the output.
        """
        # Calculate heights.
        dimensions = [c.width(cli) for c in self.children]
        sum_dimensions = _sum_layout_dimensions(dimensions)

        # If there is not enough space for both.
        # Don't do anything. (TODO: show window to small message.)
        if sum_dimensions.min > write_position.width:
            return

        # Find optimal sizes. (Start with minimal size, increase until we cover
        # the whole height.)
        sizes = [d.min for d in dimensions]
        i = 0
        while sum(sizes) < min(write_position.width, sum_dimensions.max):
            if sizes[i] < dimensions[i].max:
                sizes[i] += 1
            i = (i + 1) % len(sizes)

        # Draw child panes.
        ypos = write_position.ypos
        xpos = write_position.xpos
        min_height = write_position.min_height
        max_height = write_position.max_height

        for s, c in zip(sizes, self.children):
            c.write_to_screen(cli, screen, WritePosition(xpos, ypos, s, min_height, max_height))
            xpos += s


class Window(Layout):
    """
    Layout that holds a control.
    """
    def __init__(self, content, width=None, height=None, filter=None):
        assert isinstance(content, UIControl)
        assert width is None or isinstance(width, LayoutDimension)
        assert height is None or isinstance(height, LayoutDimension)
        assert filter is None or isinstance(filter, Filter)

        self.content = content
        self.filter = filter
        self._width = width
        self._height = height

    def __repr__(self):
        return 'Window(content=%r)' % self.content

    def reset(self):
        self.content.reset()

    def width(self, cli):
        if self.filter is None or self.filter(cli):
            return self._width or LayoutDimension()
        else:
            return LayoutDimension.exact(0)

    def height(self, cli):
        if self.filter is None or self.filter(cli):
            return self._height or LayoutDimension()
        else:
            return LayoutDimension.exact(0)

    def write_to_screen(self, cli, screen, write_position):
        # Make sure that we don't exceed the given size.
        width = self.width(cli)
        height = self.height(cli)

        # Only draw when there is enough space.
        if width.min <= write_position.width and height.min <= write_position.max_height:
            # Take as much space as possible, but not more than available.
            # For the height: take at least the minimum height, but prefer not
            # go go over `write_position.min_height`.
            container_width = min(width.max, write_position.width)
            container_height = max(height.min, min(height.max, write_position.min_height))
            container_max_height = min(height.max, write_position.max_height)

            # Set position.
            self.content.write_to_screen(
                cli, screen, WritePosition(write_position.xpos,
                                           write_position.ypos,
                                           container_width,
                                           container_height,
                                           container_max_height))
        else:
            # Show window too small messsage...
            pass


class UIControl(object):
    """
    Base class for all user interface controls.
    """
    def reset(self):
        # Default reset. (Doesn't have to be implemented.)
        pass

    @abstractmethod
    def write_to_screen(self, cli, screen, write_position):
        """
        Write the content at this position to the screen.
        """
        pass

UIControl = add_metaclass(ABCMeta)(UIControl)


class StaticControl(UIControl):
    def __init__(self, tokens):
        self.tokens = tokens

    def __repr__(self):
        return 'StaticControl(%r)' % self.tokens

    def write_to_screen(self, cli, screen, write_position):
        screen.write_at_position(self.tokens, write_position)


class FillControl(UIControl):
    """
    Fill whole control with characters with this token.
    (Also helpful for debugging.)
    """
    def __init__(self, character=' ', token=Token):
        self.token = token
        self.character = character

    def __repr__(self):
        return 'FillControl(character=%r, token=%r)' % (self.character, self.token)

    def reset(self):
        pass

    def write_to_screen(self, cli, screen, write_position):
        c = Char(char=self.character, token=self.token)

        for x in range(write_position.xpos, write_position.xpos + write_position.width):
            for y in range(write_position.ypos, write_position.ypos + write_position.min_height):
                screen.write_at_pos(y, x, c)


class ScrollContainer(UIControl):
    def __init__(self, ui_control):
        assert isinstance(ui_control, UIControl)
        self.ui_control = ui_control

    def reset(self):
        #: Vertical scrolling position of the main content.
        self.vertical_scroll = 0

    def write_to_screen(self, cli, screen, write_position):
        # Create new screen with infinite size.
        temp_screen = Screen(Size(rows=2**100, columns=write_position.width))

        # Write the control on this infinite screen.
        self.ui_control.write_to_screen(cli, temp_screen,
            WritePosition(0, 0, write_position.width, min_height=0, max_height=2**100))

        # Calculate scroll offset.
        # TODO...

        # Copy visible information to real screen.
        self._copy(temp_screen, screen, write_position)

        # Insert tildes until write_positon.min_height

        # TODO: mabye for later: pass menu position up to parent.
        pass

    def _copy(self, temp_screen, new_screen, write_position):
        columns = temp_screen.size.columns

        # Now copy the region we need to the real screen.
        for y in range(0, min(write_position.max_height, temp_screen.current_height)):
            for x in range(0, columns):
                new_screen._buffer[y + write_position.ypos][x + write_position.xpos] = temp_screen._buffer[y + self.vertical_scroll][x]

        new_screen.cursor_position = Point(y=temp_screen.cursor_position.y - self.vertical_scroll,
                                           x=temp_screen.cursor_position.x)



class BufferControl(UIControl):
    def __init__(self,
                 before_input=None,
                 after_input=None,

                 left_margin=None,
                 input_processors=None,
                 menus=None,
                 lexer=None,
                 min_height=0,
                 show_tildes=False,
                 buffer_name='default'):

        self.before_input = before_input
        self.after_input = after_input
        self.left_margin = left_margin
        self.input_processors = input_processors or []
        self.menus = menus or []
        self.min_height = min_height
        self.show_tildes = show_tildes  # XXX: tildes should become part of the left margin.
        self.buffer_name = buffer_name

        if lexer:
            self.lexer = lexer(
                stripnl=False,
                stripall=False,
                ensurenl=False)
        else:
            self.lexer = None

        #: LRU cache for the lexer.
        #: Often, due to cursor movement and undo/redo operations, it happens that
        #: in a short time, the same document has to be lexed. This is a faily easy
        #: way to cache such an expensive operation.
        self._token_lru_cache = _SimpleLRUCache(maxsize=8)

        self.reset()

    def reset(self):
        #: Vertical scrolling position of the main content.
        self.vertical_scroll = 0

    def _buffer(self, cli):
        """
        The buffer object that contains the 'main' content.
        """
        return cli.buffers[self.buffer_name]

    def get_input_tokens(self, cli):
        """
        Tokenize input text for highlighting.
        """
        buffer = self._buffer(cli)

        def get():
            if self.lexer:
                tokens = list(self.lexer.get_tokens(buffer.text))
            else:
                tokens = [(Token, buffer.text)]

            for p in self.input_processors:
                tokens = p.process_tokens(tokens)
            return tokens

        return self._token_lru_cache.get(buffer.text, get)

    def _get_highlighted_characters(self, buffer):
        """
        Return a dictionary that maps the index of input string characters to
        their Token in case of highlighting.
        """
        highlighted_characters = {}

        # In case of incremental search, highlight all matches.
        if buffer.isearch_state:
            for index in buffer.document.find_all(buffer.isearch_state.isearch_text):
                if index == buffer.cursor_position:
                    token = Token.SearchMatch.Current
                else:
                    token = Token.SearchMatch

                highlighted_characters.update(dict([
                    (x, token) for x in range(index, index + len(buffer.isearch_state.isearch_text))
                ]))

        # In case of selection, highlight all matches.
        selection_range = buffer.document.selection_range()
        if selection_range:
            from_, to = selection_range

            for i in range(from_, to):
                highlighted_characters[i] = Token.SelectedText

        return highlighted_characters

#    def write_to_screen(self, cli, screen, write_position):
#        #if self.before_input is not None:
#        #    self.before_input.write(cli, screen)
#
#        y = self._write_input_scrolled(cli, screen,
#                                      lambda scr: self.write_content(cli, scr),
#                                      min_height=max(self.min_height, min_height),


  #  def write_content(

  #      self._write_input(cli, screen)
  #      #if self.after_input is not None:
  #      #    self.after_input.write(cli, screen)
    def _write_input(self, cli, screen):
        # Get tokens
        # Note: we add the space character at the end, because that's where
        #       the cursor can also be.
        input_tokens = self.get_input_tokens(cli) + [(Token, ' ')]

        # 'Explode' tokens in characters.
        input_tokens = [(token, c) for token, text in input_tokens for c in text]

        # Apply highlighting.
        if not (cli.is_exiting or cli.is_aborting or cli.is_returning):
            highlighted_characters = self._get_highlighted_characters(self._buffer(cli))

            for index, token in highlighted_characters.items():
                input_tokens[index] = (token, input_tokens[index][1])

        for index, (token, c) in enumerate(input_tokens):
            # Insert char.
            screen.write_char(c, token,
                              string_index=index,
                              set_cursor_position=(index == self._buffer(cli).cursor_position))


    def write_to_screen(self, cli, screen, write_position):
#    def _write_input_scrolled(self, cli, screen, write_position):
#            write_content,
#                             min_height=1, top_margin=0, bottom_margin=0):
        """
        Write visible part of the input to the screen. (Scroll if the input is
        too large.)

        :return: Cursor row position after the scroll region.
        """
        left_margin_width = self.left_margin.width(cli) if self.left_margin else 0

#        # Make sure that `min_height` is in the 0..max_height interval.
#        min_height = min(min_height, screen.size.rows)
#        min_height = max(0, min_height)
#
        # Write to a temp screen first. (Later, we will copy the visible region
        # of this screen to the real screen.)
        temp_screen = Screen(Size(columns=screen.size.columns - left_margin_width,
                                  rows=screen.size.rows))
        self._write_input(cli, temp_screen)

        # Determine the maximum height.
#        max_height = screen.size.rows - bottom_margin - top_margin
        max_height = write_position.max_height

        # Scroll.
        if True:
            # Scroll back if we scrolled to much and there's still space at the top.
            if self.vertical_scroll > temp_screen.current_height - max_height:
                self.vertical_scroll = max(0, temp_screen.current_height - max_height)

            # Scroll up if cursor is before visible part.
            if self.vertical_scroll > temp_screen.cursor_position.y:
                self.vertical_scroll = temp_screen.cursor_position.y

            # Scroll down if cursor is after visible part.
            if self.vertical_scroll <= temp_screen.cursor_position.y - max_height:
                self.vertical_scroll = (temp_screen.cursor_position.y + 1) - max_height

            # Scroll down if we need space for the menu.
            if self._need_to_show_completion_menu(cli):
                menu_size = self.menus[0].get_height(self._buffer(cli).complete_state)
                if temp_screen.cursor_position.y - self.vertical_scroll >= max_height - menu_size:
                    self.vertical_scroll = (temp_screen.cursor_position.y + 1) - (max_height - menu_size)

        # Now copy the region we need to the real screen.
        y = 0
        for y in range(0, min(max_height, temp_screen.current_height - self.vertical_scroll)):
            if self.left_margin:
                # Write left margin. (XXX: line numbers are still not correct in case of line wraps!!!)
                screen._y = y
                screen._x = 0
                self.left_margin.write(cli, screen, y, y + self.vertical_scroll)

            # Write line content.
            for x in range(0, temp_screen.size.columns):
                screen._buffer[y][x + left_margin_width] = temp_screen._buffer[y + self.vertical_scroll][x]

        screen.cursor_position = Point(y=temp_screen.cursor_position.y - self.vertical_scroll,
                                       x=temp_screen.cursor_position.x + left_margin_width)

        y_after_input = y

        # Show completion menu.
        if self._need_to_show_completion_menu(cli):
            try:
                y, x = temp_screen._cursor_mappings[self._buffer(cli).complete_state.original_document.cursor_position]
            except KeyError:
                # This happens when the new, completed string is shorter than
                # the original string. (e.g. in case of useless backslash
                # escaping that is removed by the autocompleter.)
                # Not worth fixing at the moment. Just don't show the menu.
                pass
            else:
                self.menus[0].write(screen, (y - self.vertical_scroll, x + left_margin_width), self._buffer(cli).complete_state)

        return_value = max([min_height, screen.current_height])

        # Fill up with tildes.
        if self.show_tildes:
            y = y_after_input + 1
            max_ = max([min_height, screen.current_height])
            while y < max_:
                screen.write_at_pos(y, 1, Char('~', Token.Layout.Tilde))
                y += 1

        return return_value



class OldLayout(object):
    """
    Default prompt class.

    :param before_input: What to show before the actual input.
    :param input_processors: Processors for transforming the tokens received
                             from the `Code` object. (This can be used for
                             displaying password input as '*' or for
                             highlighting mismatches of brackets in case of
                             Python input.)
    :param menus: List of `Menu` classes or `None`.
    """
    def __init__(self,
                 before_input=None,
                 after_input=None,
                 left_margin=None,
                 top_toolbars=None,
                 bottom_toolbars=None,
                 input_processors=None,
                 menus=None,
                 lexer=None,
                 min_height=0,
                 show_tildes=False,
                 buffer_name='default'):

        self.before_input = before_input
        self.after_input = after_input
        self.left_margin = left_margin
        self.top_toolbars = top_toolbars or []
        self.bottom_toolbars = bottom_toolbars or []
        self.input_processors = input_processors or []
        self.menus = menus or []
        self.min_height = min_height
        self.show_tildes = show_tildes
        self.buffer_name = buffer_name

        if lexer:
            self.lexer = lexer(
                stripnl=False,
                stripall=False,
                ensurenl=False)
        else:
            self.lexer = None

        #: LRU cache for the lexer.
        #: Often, due to cursor movement and undo/redo operations, it happens that
        #: in a short time, the same document has to be lexed. This is a faily easy
        #: way to cache such an expensive operation.
        self._token_lru_cache = _SimpleLRUCache(maxsize=8)

        self.reset()

    def _buffer(self, cli):
        """
        The buffer object that contains the 'main' content.
        """
        return cli.buffers[self.buffer_name]

    def reset(self):
        #: Vertical scrolling position of the main content.
        self.vertical_scroll = 0

    def get_input_tokens(self, cli):
        """
        Tokenize input text for highlighting.
        """
        buffer = self._buffer(cli)

        def get():
            if self.lexer:
                tokens = list(self.lexer.get_tokens(buffer.text))
            else:
                tokens = [(Token, buffer.text)]

            for p in self.input_processors:
                tokens = p.process_tokens(tokens)
            return tokens

        return self._token_lru_cache.get(buffer.text, get)

    def _get_highlighted_characters(self, buffer):
        """
        Return a dictionary that maps the index of input string characters to
        their Token in case of highlighting.
        """
        highlighted_characters = {}

        # In case of incremental search, highlight all matches.
        if buffer.isearch_state:
            for index in buffer.document.find_all(buffer.isearch_state.isearch_text):
                if index == buffer.cursor_position:
                    token = Token.SearchMatch.Current
                else:
                    token = Token.SearchMatch

                highlighted_characters.update(dict([
                    (x, token) for x in range(index, index + len(buffer.isearch_state.isearch_text))
                ]))

        # In case of selection, highlight all matches.
        selection_range = buffer.document.selection_range()
        if selection_range:
            from_, to = selection_range

            for i in range(from_, to):
                highlighted_characters[i] = Token.SelectedText

        return highlighted_characters

    def _write_input(self, cli, screen):
        # Get tokens
        # Note: we add the space character at the end, because that's where
        #       the cursor can also be.
        input_tokens = self.get_input_tokens(cli) + [(Token, ' ')]

        # 'Explode' tokens in characters.
        input_tokens = [(token, c) for token, text in input_tokens for c in text]

        # Apply highlighting.
        if not (cli.is_exiting or cli.is_aborting or cli.is_returning):
            highlighted_characters = self._get_highlighted_characters(self._buffer(cli))

            for index, token in highlighted_characters.items():
                input_tokens[index] = (token, input_tokens[index][1])

        for index, (token, c) in enumerate(input_tokens):
            # Insert char.
            screen.write_char(c, token,
                              string_index=index,
                              set_cursor_position=(index == self._buffer(cli).cursor_position))


    def _need_to_show_completion_menu(self, cli):
        return self.menus and self.menus[0].is_visible(cli)

    def write_to_screen(self, cli, screen, min_height):
        """
        Render the prompt to a `Screen` instance.

        :param screen: The :class:`Screen` class into which we write the output.
        :param min__height: The space (amount of rows) available from the
                            top of the prompt, until the bottom of the
                            terminal. We don't have to use them, but we can.
        """

        # Write actual content (scrolled).
        y = self._write_input_scrolled(cli, screen,
                                      lambda scr: self.write_content(cli, scr),
                                      min_height=max(self.min_height, min_height),
                                      top_margin=top_toolbars_height,
                                      bottom_margin=bottom_toolbars_height)

    def write_content(self, cli, screen):
        """
        Write the actual content at the current position at the screen.
        """
        if self.before_input is not None:
            self.before_input.write(cli, screen)

        self._write_input(cli, screen)

        if self.after_input is not None:
            self.after_input.write(cli, screen)
