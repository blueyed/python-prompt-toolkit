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


@add_metaclass(ABCMeta)
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

        self.reset()

    def __repr__(self):
        return 'Window(content=%r)' % self.content

    def reset(self):
        self.content.reset()

        #: Vertical scrolling position of the main content.
        self.vertical_scroll = 0

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

#            write_position = WritePosition(write_position.xpos,
#                                           write_position.ypos,
#                                           container_width,
#                                           container_height,
#                                           container_max_height))

            # Set position.
            temp_screen = self._write_to_temp_screen(cli, container_width, container_height)
            self._copy(temp_screen, screen, write_position.xpos, write_position.ypos, container_width, container_height)

        else:
            # Show window too small messsage...
            pass

    def _write_to_temp_screen(self, cli, width, height):
        # Create new screen with infinite size.
        temp_screen = Screen(Size(rows=2**1000, columns=width))

        # Write the control on this infinite screen.
        self.content.write_to_screen(cli, temp_screen, width, height)

        return temp_screen

    def _copy(self, temp_screen, new_screen, xpos, ypos, width, height):
        columns = temp_screen.size.columns

        temp_buffer = temp_screen._buffer
        new_buffer = new_screen._buffer

        # Now copy the region we need to the real screen.
        for y in range(0, min(height, temp_screen.current_height)):
            # We keep local row variables. (Don't look up the row in the dict
            # for each iteration of the nested loop.)
            temp_row = temp_buffer[y + self.vertical_scroll]
            new_row = new_buffer[y + ypos]

                # XXX: if we don't use nested default dicts, we can do:
                #      a[xpos:xpos+columns] = b[0:columns]
            for x in range(0, columns):
                new_row[x + xpos] = temp_row[x]

#        new_screen.cursor_position = Point(y=temp_screen.cursor_position.y - self.vertical_scroll,
#                                           x=temp_screen.cursor_position.x)


        """
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
        """



@add_metaclass(ABCMeta)
class UIControl(object):
    """
    Base class for all user interface controls.
    """
    def reset(self):
        # Default reset. (Doesn't have to be implemented.)
        pass

    @abstractmethod
    def write_to_screen(self, cli, screen, width, height):
        """
        Write the content at this position to the screen.
        """
        pass


class StaticControl(UIControl):
    def __init__(self, tokens):
        self.tokens = tokens

    def __repr__(self):
        return 'StaticControl(%r)' % self.tokens

    def write_to_screen(self, cli, screen, width, height):
        screen.write_at_position(self.tokens, WritePosition(0, 0, width, height))


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

    def write_to_screen(self, cli, screen, width, height):
        c = Char(char=self.character, token=self.token)

        for x in range(0, width):
            for y in range(0, height):
                screen.write_at_pos(y, x, c)


class BufferControl(UIControl):
    def __init__(self,
                 before_input=None,
                 after_input=None,

                 left_margin=None,
                 input_processors=None,
                 menus=None,
                 lexer=None,
                 show_tildes=False,
                 show_line_numbers=True,
                 buffer_name='default'):

        self.before_input = before_input
        self.after_input = after_input
        self.left_margin = left_margin
        self.input_processors = input_processors or []
        self.menus = menus or []
        self.show_tildes = show_tildes  # XXX: tildes should become part of the left margin.
        self.show_line_numbers = show_line_numbers
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


    def write_to_screen(self, cli, screen, width, height):
        """
        Write visible part of the input to the screen. (Scroll if the input is
        too large.)

        :return: Cursor row position after the scroll region.
        """
        left_margin_width = self.left_margin.width(cli) if self.left_margin else 0
#

#        screen.write_highlighted([
#            (Token.LineNumber, '%%%ii. ' % (self.width(cli) - 2) % (line_number + 1)),
#        ])


        self._write_input(cli, screen)


        screen.cursor_position = Point(y=screen.cursor_position.y,
                                       x=screen.cursor_position.x + left_margin_width)

        return # XXX

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
