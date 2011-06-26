#!/usr/bin/env python
# -*- coding: utf-8 -*-

# ease eventual Python 3 transition
from __future__ import division, print_function, unicode_literals

import os, sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/../pym')

from plagwiki.config import Config
from plagwiki.loaders.emergencyerror import EmergencyError
from copy import copy
import HTMLParser
import htmlentitydefs
import io
import pprint
import re
import urlparse


class HTMLStructuralParser(HTMLParser.HTMLParser):
    EMPTY_TAGS = set(('area', 'base', 'basefont', 'br', 'col', 'frame',
        'hr', 'img', 'input', 'isindex', 'link', 'meta', 'param'))

    def __init__(self):
        HTMLParser.HTMLParser.__init__(self)
        self.reset()

    def reset(self):
        HTMLParser.HTMLParser.reset(self)
        self.__tagstack = [('', {}, [])]
        self.__pre_count = 0

    def get_structure(self):
        return self.__tagstack[0][2]

    def handle_starttag(self, tag, attrs):
        # Create a tuple that represents the new tag.
        tagtuple = (tag, dict(attrs), [])

        # Add the new tag to the children list of the parent tag.
        self.__tagstack[-1][2].append(tagtuple)

        # Also append the new tag to the end of the tag stack,
        # in order to make this tag the 'current parent' from now on
        self.__tagstack.append(tagtuple)

        # <pre></pre> require special handling in handle_data(),
        # so count them
        if tag == 'pre':
            self.__pre_count += 1

        # For tags like <br>, <img> etc. also call handle_endtag,
        # because HTMLParser doesn't do it for us
        if tag in HTMLStructuralParser.EMPTY_TAGS:
            self.__handle_endtag_or_emptytag(tag)

    def handle_endtag(self, tag):
        if tag in HTMLStructuralParser.EMPTY_TAGS:
            raise RuntimeError('Tag '+tag+' can\'t be closed using </'+tag+'>, use <'+tag+' /> instead')
        self.__handle_endtag_or_emptytag(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in HTMLStructuralParser.EMPTY_TAGS:
            self.__handle_endtag_or_emptytag(tag)

    def __handle_endtag_or_emptytag(self, tag):
        if len(self.__tagstack) <= 1 or self.__tagstack[-1][0] != tag:
            raise RuntimeError('Tag <'+tag+'> cannot be closed because it is not open')
        if tag == 'pre':
            self.__pre_count -= 1
        self.__tagstack.pop()

    def handle_data(self, data):
        if not self.__pre_count:
            data = re.sub('\s+', ' ', data)  # collapse spaces
        self.__tagstack[-1][2].append(data)

    def handle_charref(self, name):
        self.handle_data(unichr(int(name)))

    def handle_entityref(self, name):
        if name in htmlentitydefs.name2codepoint:
            self.handle_data(unichr(htmlentitydefs.name2codepoint[name]))
        else:
            self.handle_data('&' + name + ';')


class OpenStruct(object):
    pass


class LaTeXTableGenerator(object):
    def __init__(self):
        self._cells = dict()
        self._rowtag = None
        self._rowattrs = None
        self._column_width_constraints = []
        self._caption = ''
        self._caption_below = False
        self._nested_caption = ''
        self._nested_caption_below = False
        self._x = 0
        self._y = 0

    def add_caption(self, text):
        self._caption = text
        self._caption_below = bool(self._cells)  # is the table nonempty?

    def get_caption(self):
        if self._caption:
            return (self._caption, self._caption_below)
        else:
            return (self._nested_caption, self._nested_caption_below)

    def add_nested_table_caption(self, nested_table):
        self._nested_caption, self._nested_caption_below = nested_table.get_caption()

    def start_row(self, tag, attrs):
        assert tag in ('tr', 'thead', 'tfoot')
        self._rowtag = tag
        self._rowattrs = attrs
        self._x = 0
        self._y += 1

    def end_row(self):
        self._rowtag = None
        self._rowattrs = None

    def is_row_started(self):
        return self._rowtag is not None

    def add_cell(self, tag, attrs, text):
        assert tag in ('td', 'th')
        assert self.is_row_started()
        self._x += 1
        while (self._x, self._y) in self._cells:
            self._x += 1

        is_header_cell = (tag == 'th' or self._rowtag == 'thead' or self._rowtag == 'tfoot')
        if is_header_cell:
            text = '\\textbf{' + text + '}'

        colspan = rowspan = 1
        if 'colspan' in attrs:
            colspan = max(int(attrs['colspan']), 1)
        if 'rowspan' in attrs:
            rowspan = max(int(attrs['rowspan']), 1)

        # FIXME: This is a hack. A very horrible hack, indeed. But it works.
        background_color = None
        text_align = None
        vertical_align = None
        width = None
        all_styles = [x['style'] for x in [self._rowattrs, attrs] if 'style' in x]
        for style in all_styles:
            match = re.search('background-color\s*:\s*([^;]+)', style)
            if match:
                background_color = match.group(1)
            match = re.search('text-align\s*:\s*([^;]+)', style)
            if match and match.group(1) in ('left', 'center', 'right'):
                text_align = match.group(1)
            match = re.search('vertical-align\s*:\s*([^;]+)', style)
            if match and match.group(1) in ('top', 'middle', 'bottom'):
                vertical_align = match.group(1)
            match = re.search('width\s*:\s*(\d+(\.\d+)?)%', style)
            if match:
                width = 0.01*float(match.group(1))

        if background_color is not None:
            background_rgb = self._css_color_to_rgb(background_color)
        elif is_header_cell:
            background_rgb = self._css_color_to_rgb('#f2f2f2')
        else:
            background_rgb = None

        if text_align is None:
            text_align = 'center' if is_header_cell else 'left'

        if vertical_align is None:
            vertical_align = 'top'

        if width is not None:
            self._column_width_constraints.append((range(self._x, self._x + colspan), width))

        for x in range(self._x, self._x + colspan):
            for y in range(self._y, self._y + rowspan):
                cell = OpenStruct()
                cell.text = text
                cell.is_left = (x == self._x)
                cell.is_bottom = (y == self._y + rowspan - 1)
                cell.is_main = (cell.is_left and cell.is_bottom)
                cell.colspan = colspan
                cell.rowspan = rowspan
                cell.background_rgb = background_rgb  # None or RGB-float string
                cell.text_align = text_align  # left, center or right
                cell.vertical_align = vertical_align  # top, middle or bottom
                self._cells[(x, y)] = cell


    def _css_color_to_rgb(self, csscolor):
        # TODO: add support for named colors
        if re.match('^#[0-9a-zA-Z]{6}$', csscolor):
            r = int(csscolor[1:3], 16) / 255.0
            g = int(csscolor[3:5], 16) / 255.0
            b = int(csscolor[5:7], 16) / 255.0
            return "%1.3f,%1.3f,%1.3f" % (r,g,b)
        elif re.match('^#[0-9a-zA-Z]{3}$', csscolor):
            r = int(csscolor[1:2], 16) / 15.0
            g = int(csscolor[2:3], 16) / 15.0
            b = int(csscolor[3:4], 16) / 15.0
            return "%1.3f,%1.3f,%1.3f" % (r,g,b)
        else:
            return None

    def print_latex_table(self, width, file=sys.stdout):
        caption, caption_below = self.get_caption()
        file.write(r'\begin{table}[htbp]' + '\n')
        file.write(r'\centering' + '\n')
        if caption and not caption_below:
            file.write(r'\caption{' + self._caption + '}\n')
        self.print_latex_tabular(width, file)
        if caption and caption_below:
            file.write('\\caption{' + self._caption + '}\n')
        file.write(r'\end{table}' + '\n')

    def print_latex_tabular(self, width, file=sys.stdout):
        # compute maximum cell indices
        if self._cells:
            xmax = max(k[0] for k in self._cells.keys())
            ymax = max(k[1] for k in self._cells.keys())
        else:
            xmax = ymax = 0
        if xmax == 0 or ymax == 0:
            return

        # compute column widths from constraints
        column_widths = {}
        self._column_width_constraints.sort(key = lambda x: len(x[0]))
        #pprint.pprint(self._column_width_constraints)
        for constraint_columns, constraint_width in self._column_width_constraints:
            if not constraint_columns:
                continue
            constraint_cur_widths = [column_widths.get(x, None) for x in constraint_columns]
            constraint_cur_totalwidth = sum([column_widths.get(x, 0.0) for x in constraint_columns])
            if None in constraint_cur_widths or constraint_cur_totalwidth < constraint_width:
                addwidth = max(0.0, (constraint_width - constraint_cur_totalwidth) / len(constraint_columns))
                for x in constraint_columns:
                    column_widths[x] = max(0.0, column_widths.get(x, 0.0) + addwidth)
        if len(column_widths) != xmax:
            addwidth = max(0.0, (1.0 - sum(column_widths.values())) / (xmax - len(column_widths)))
            for x in range(1, xmax+1):
                if x not in column_widths:
                    column_widths[x] = addwidth
        addwidth = max(0.0, (1.0 - sum(column_widths.values())) / xmax)
        column_widths_cm = {}
        for x in range(1, xmax+1):
            column_widths_cm[x] = max(0.1, width * (column_widths[x] + addwidth))
        #pprint.pprint(column_widths_cm)

        # start of tabular and column specifications
        #file.write(r'\centering' + '\n')
        file.write(r'\begin{longtable}{|')
        for x in range(1, xmax+1):
            #file.write(r'>{\raggedrightarraybackslash}p{' + unicode(column_widths_cm[x]) + 'cm}|')
            file.write('p{' + unicode(column_widths_cm[x]) + 'cm}|')
        file.write('p{0cm}')
        file.write('}\n')
        file.write(r'\hline' + '\n')

        # write the tabular rows
        for y in range(1, ymax+1):
            for x in range(1, xmax+1):
                self._print_cell(x, y, column_widths_cm, file)
            #if y != ymax:
            #    print hline
            file.write(r'\\'+'\n')

        # end of tabular
        file.write(r'\hline' + '\n')
        file.write(r'\end{longtable}' + '\n')

    def _print_cell(self, x, y, column_widths_cm, file):
        cell = self._cells.get((x, y), None)
        if cell is not None and cell.is_left:
            #if x != 1:
            #    file.write('& ')
            if cell.is_main:
                text = cell.text
            else:
                text = '~'
            parbox_width = sum(column_widths_cm[z] for z in range(x, x+cell.colspan))
            parbox_halign = ''
            parbox_halign_end = ''
            parbox_valign = ''
            if cell.text_align == 'left':
                #parbox_halign = r'\begin{flushleft}'
                #parbox_halign_end = r'\end{flushleft}'
                pass
            elif cell.text_align == 'center':
                #parbox_halign = '\centering{}'
                pass
            else:
                #parbox_halign = r'\begin{flushright}'
                #parbox_halign_end = r'\end{flushright}'
                pass
            if cell.vertical_align == 'top':
                parbox_valign = '[t]'
            elif cell.vertical_align == 'bottom':
                parbox_valign = '[b]'
            text = parbox_halign + r'\parbox' + parbox_valign + '{' + unicode(parbox_width) + 'cm}{' + text + '}' + parbox_halign_end
            if cell.background_rgb != None:
                text = r'\cellcolor[rgb]{' + cell.background_rgb + '}' + text
            if cell.is_main and cell.rowspan != 1:
                text = r'\multirow{-' + unicode(cell.rowspan) + '}{*}{' + text + '}'
            if cell.colspan != 1:
                text = r'\multicolumn{' + unicode(cell.colspan) + '}{p{' + unicode(parbox_width) + 'cm}}{' + text + '}'

        #effective_cellcolor = 'transparent'
        #if effective_cellcolor != 'transparent' or effective_align not in ('|l|', 'l|') or colspan != 1:
        #    #main_cell_contents = '\\raggedright ' + main_cell_contents
        #    if effective_cellcolor != 'transparent':
        #        main_cell_contents = '\\cellcolor[rgb]{' + effective_cellcolor + '}' + main_cell_contents
        #        above_cell_contents = '\\cellcolor[rgb]{' + effective_cellcolor + '}' + above_cell_contents
        #    main_cell_contents = '\\multicolumn{' + unicode(colspan) + '}{' + effective_align + '}{' + main_cell_contents + '}'
        #    above_cell_contents = '\\multicolumn{' + unicode(colspan) + '}{' + effective_align + '}{' + above_cell_contents + '}'
        #
        #for x in range(self._x, self._x + colspan):
        #    for y in range(self._y, self._y + rowspan):
        #        if x == self._x:
        #            cellprefix = '' if x == 1 else '& '
        #            if y == self._y + rowspan - 1:
        #                self._cells[(x, y)] = cellprefix + main_cell_contents
        #            else:
        #                self._cells[(x, y)] = cellprefix + above_cell_contents
        #        else:
        #            self._cells[(x, y)] = ''
            file.write(text)
            file.write(' &')


class HTMLToLaTeX(object):
    def convert(html, baseurl, verbose):
        converter = HTMLToLaTeX(html, baseurl, verbose)
        converter.process()  # get citations correct
        converter.process()  # get final text correct
        return converter.get_output()
    convert = staticmethod(convert)

    def convert_and_print(html, baseurl, verbose, file=sys.stdout):
        converter = HTMLToLaTeX(html, baseurl, verbose)
        try:
            converter.process()  # get citations correct
            converter.process()  # get final text correct
        finally:
            print(converter.get_output().encode('utf-8'), file=file)
    convert_and_print = staticmethod(convert_and_print)

    def __init__(self, html, baseurl, verbose):
        structural_parser = HTMLStructuralParser()
        structural_parser.feed(html)
        structural_parser.close()
        self._structure = structural_parser.get_structure()
        self._baseurl = baseurl
        self._verbose = verbose
        self._output = io.StringIO()
        self._citations = {}
        self._fixup_dict = None
        self._fixup_pattern = None
        self._preprocess('', self._structure)
        if verbose:
            pprint.pprint(self._structure)

    def get_output(self):
        return self._output.getvalue()

    def _preprocess(self, tag, children):
        for i in range(len(children)):
            if isinstance(children[i], tuple):
                assert len(children[i]) == 3
                if tag == 'table' and children[i][0] not in ('tr', 'thead', 'tfoot', 'caption'):
                    children[i] = ('tr', {}, [('td', {}, [children[i]])])
                elif tag in ('tr', 'thead', 'tfoot') and children[i][0] not in ('td', 'th'):
                    children[i] = ('td', {}, [children[i]])
                self._preprocess(children[i][0], children[i][2])

    def process(self):
        self._output.seek(0)
        self._output.truncate()

        context = OpenStruct()
        context.out = self._output
        context.in_verbatim = False
        context.in_references = False
        context.in_cite_ref = False
        context.name_cite_ref = None
        context.dl_started = False
        context.table = None
        self._process_list(self._structure, context)

    def _debug(self, message, context):
        if self._verbose and not context.in_verbatim:
            self._output.write('% ' + message + "\n")

    def _process_list(self, lis, context, prepend=None, append=None):
        if prepend is not None:
            context.out.write(prepend)
        for elem in lis:
            if isinstance(elem, tuple):
                assert len(elem) == 3
                tag, attrs, children = elem
                self._process_tag(tag, attrs, children, context)
            else:
                assert isinstance(elem, unicode)
                self._process_data(elem, context)
        if append is not None:
            context.out.write(append)

    def _process_data(self, data, context):
        context.out.write(self._tex_fixup_text(data))

    def _process_tag(self, tag, attrs, children, context):
        # convert attributes into a more usable format
        if 'class' in attrs:
            attrs_classes = set(attrs['class'].split())
        else:
            attrs_classes = set()

        # provide a mechanism to ignore everything below specific tags
        if tag == 'span' and 'editsection' in attrs_classes:
            self._debug('Ignoring editsection span', context)
            return
        if tag == 'table' and 'infobox' in attrs_classes:
            self._debug('Ignoring infobox table', context)
            return
        if tag == 'table' and 'toc' in attrs_classes:
            self._debug('Ignoring toc table', context)
            return
        if tag == 'script':
            self._debug('Ignoring script', context)
            return
        if (tag == 'a' and 'image' in attrs_classes) or (tag == 'img'):
            # FIXME
            self._debug('Ignoring image', context)
            return
        if 'style' in attrs and re.search(r'display\s*:\s*none\b', attrs['style']):
            self._debug('Ignoring '+tag+' because of display: none', context)
            return

        self._debug('Encountered a '+tag+' tag', context)
        if attrs:
            self._debug('  Attributes: ' + repr(attrs), context)

        if tag == 'h1':
            self._process_list(children, context, r'\part{', '}\n')
        elif tag == 'h2':
            self._process_list(children, context, r'\section{', '}\n')
        elif tag == 'h3':
            self._process_list(children, context, r'\subsection{', '}\n')
        elif tag == 'h4':
            self._process_list(children, context, r'\subsubsection{', '}\n')
        elif tag == 'h5':
            self._process_list(children, context, r'\paragraph{', '}\n')
        elif tag == 'h6':
            self._process_list(children, context, r'\subparagraph{', '}\n')
        elif tag == 'p':
            if context.table is None:
                while context.out.getvalue()[-2:] != '\n\n':
                    context.out.write('\n')
            self._process_list(children, context)
            if context.table is None:
                while context.out.getvalue()[-2:] != '\n\n':
                    context.out.write('\n')
        elif tag == 'br':
            if context.table is None:
                context.out.write(r'\ifhmode\\\fi' + '\n')
            else:
                #context.out.write(r'\ifhmode\newline\fi' + '\n')
                context.out.write(r'\newline' + '\n')
        elif tag == 'pre':
            context.out.write(r'\begin{verbatim}'+'\n')
            context2 = copy(context)
            context2.in_verbatim = True
            self._process_list(children, context2)
            context.out.write(r'\end{verbatim}'+'\n')
        elif tag == 'div':
            # TODO implement div
            # interpret style?
            self._process_list(children, context)
        elif tag == 'span':
            # TODO implement span
            # interpret style?
            # define bookmark when 'mw-headline' in attr_classes?
            self._process_list(children, context)
        elif tag == 'a':
            if 'href' in attrs:
                href = re.sub('&amp;', '&', attrs['href'])
                if context.in_cite_ref:
                    # This links to a reference
                    context.name_cite_ref = re.sub('^#', '', href)
                elif context.in_references and href[0:1] == '#' and \
                        children == ['\u2191']:
                    # This is a backlink from a reference
                    pass
                elif len(children) == 1 and href == children[0]:
                    # This is a normal link with link text == href
                    url = urlparse.urljoin(self._baseurl, href)
                    context.out.write('\\url{' + self._tex_fixup_url(url) + '}')
                else:
                    # This is a normal link
                    url = urlparse.urljoin(self._baseurl, href)
                    self._process_list(children, context,
                            r'\href{' + self._tex_fixup_url(url) + '}{', '}')
        elif tag == 'b' or tag == 'strong':
            self._process_list(children, context, r'\textbf{', '}')
        elif tag == 'i':
            self._process_list(children, context, r'\textit{', '}')
        elif tag == 'em':
            self._process_list(children, context, r'\emph{', '}')
        elif tag == 'u':
            # can't use r'\underline{' because \u is an escape even in raw
            self._process_list(children, context, '\\underline{', '}')
        elif tag == 'tt':
            self._process_list(children, context, '\\texttt{', '}')
        elif tag == 'big':
            self._process_list(children, context, '\\underline{', '}')
        elif tag == 'big':
            self._process_list(children, context, '{\\large ', '}')
        elif tag == 'small':
            self._process_list(children, context, '{\\small ', '}')
        elif tag == 'sup':
            if 'reference' in attrs_classes:
                context2 = copy(context)
                context2.out = io.StringIO()  # temp redirect to /dev/null
                context2.in_cite_ref = True
                context2.name_cite_ref = None
                self._process_list(children, context2)
                if context2.name_cite_ref in self._citations:
                    context.out.write(r'\footnote{')
                    context.out.write(self._citations[context2.name_cite_ref].getvalue())
                    context.out.write('}')
            else:
                self._process_list(children, context, r'\textsuperscript{', '}')
        elif tag == 'sub':
            # \textsubscript is in LaTeX package fixltx2e
            self._process_list(children, context, r'\textsubscript{', '}')
        elif tag == 'ul':
            self._process_list(children, context,
                    r'\begin{itemize}'+'\n', r'\end{itemize}'+'\n')
        elif tag == 'ol':
            if 'references' in attrs_classes:
                context2 = copy(context)
                context2.out = io.StringIO  # temp redirect to /dev/null
                context2.in_references = True
                self._process_list(children, context2)
            else:
                self._process_list(children, context,
                        r'\begin{enumerate}'+'\n',
                        r'\end{enumerate}'+'\n')
        elif tag == 'li':
            if context.in_references and 'id' in attrs:
                # process a reference; we store the tex output in a StringIO
                # object in self._citations, which is kept around between
                # the first parser phase and the second
                # this allows us to correctly convert (to a \footnote)
                # references that are printed later than from where they
                # are linked from (that is, most references)
                reference_string_io = io.StringIO()
                self._citations[attrs['id']] = reference_string_io
                context2 = copy(context)
                context2.out = reference_string_io
                self._process_list(children, context2)
            else:
                self._process_list(children, context, r'\item ', '\n')
        elif tag == 'dl':
            context.dl_started = False
            self._process_list(children, context,
                    r'\begin{description}'+'\n', r'\end{description}'+'\n')
        elif tag == 'dt':
            context.dl_started = True
            self._process_list(children, context, r'\item[', ']')
        elif tag == 'dd':
            if not context.dl_started:
                context.out.write('\item ')
                context.dl_started = True
            self._process_list(children, context)
        elif tag == 'blockquote':
            self._process_list(children, context,
                    r'\begin{quote}'+'\n', r'\end{quote}'+'\n')
        elif tag == 'hr':
            context.out.write('\hrulesep{}')
        elif tag == 'table':
            table_generator = LaTeXTableGenerator()
            context2 = copy(context)
            context2.out = io.StringIO()  # temp redirect to /dev/null
            context2.table = table_generator
            self._process_list(children, context2)
            if context.table is None:
                # outermost table
                table_generator.print_latex_table(width=13.0, file=context.out)
            else:
                # nested table
                print('OH NOES', file=sys.stderr)
                raise RuntimeError('Somebody set up us the nested table. We are on the way to destruction. We have no chance to survive make our time.')
                #context.out.write(r'\mbox{')
                #table_generator.print_latex_tabular(width=12.0, file=context.out)
                #context.out.write(r'}')
        elif tag == 'caption':
            if context.table is None:
                raise RuntimeError(tag + ' encountered outside table')
            context.out.seek(0)
            context.out.truncate()
            self._process_list(children, context)
            context.table.add_caption(context.out.getvalue())
        elif tag in ('tr', 'thead', 'tfoot'):
            if context.table is None:
                raise RuntimeError(tag + ' encountered outside table')
            context.table.start_row(tag, attrs)
            self._process_list(children, context)
            context.table.end_row()
        elif tag in ('td', 'th'):
            if context.table is None:
                raise RuntimeError(tag + ' encountered outside table')
            if not context.table.is_row_started():
                raise RuntimeError(tag + ' encountered outside table row')
            context.out.seek(0)
            context.out.truncate()
            self._process_list(children, context)
            context.table.add_cell(tag, attrs, context.out.getvalue())
        else:
            raise RuntimeError('Tag not supported: '+tag)

    def _tex_fixup_text(self, text):
        if self._fixup_dict is None:
            # we replace all TeX control characters, everything in textcomp
            # and some misc stuff
            self._fixup_dict = {
                    '\\': '\\textbackslash{}',
                    '{': '\{',
                    '}': '\}',
                    '"': '\\textquotedbl{}',
                    '&': '\&', 
                    '#': '\#',
                    '%': '\%',
                    '_': '\_',
                    '^': '\^{}',
                    '$': '\$',
                    '[': '$[$',
                    ']': '$]$',
                    '~': '\~{}',
                    '\xa0': '~',                    # non-breaking space
                    '\xac': r'\textlnot{}',         # ¬
                    '\xb0': r'\textdegree{}',       # °
                    '\xb1': r'\textpm{}',           # ±
                    '\xb2': r'\texttwosuperior{}',  # ²
                    '\xb3': r'\textthreesuperior{}',# ³
                    '\xb4': r'\'{}',                # ´
                    '\xb9': r'\textonesuperior{}',  # ¹
                    '\xbc': r'\textonequarter{}',   # ¼
                    '\xbd': r'\textonehalf{}',      # ½
                    '\xbe': r'\textthreequarters{}',# ¾
                    '\xd7': r'\texttimes{}',        # ×
                    '\xf7': r'\textdiv{}',          # ÷
                    '\u2044': r'\textfractionsolidus{}', # ⁄
                    '\u2190': r'\textleftarrow{}',  # ←
                    '\u2191': r'\textuparrow{}',    # ↑
                    '\u2192': r'\textrightarrow{}', # →
                    '\u2193': r'\textdownarrow{}',  # ↓
                    '\u2212': r'\textminus{}',      # minus sign
                    '\u221a': r'\textsurd{}',       # √
                    '\ufb01': 'fi',                 # ﬁ
                    '\ufb02': 'fl',                 # ﬂ
                    ' - ': ' --- ',                 # ascii hyphen misused as dash
                    '\u2010': '---',                # hyphen
                    '\u2011': '---',                # non-breaking hyphen
                    '\u2012': '---',                # figure dash
                    '\u2013': '---',                # en dash
                    '\u2014': '---',                # em dash
                    '\u2015': '---',                # horizontal bar
                    }
            self._fixup_pattern = re.compile('(' + '|'.join(re.escape(x) for x in self._fixup_dict) + ')')
            self._fixup_repl = lambda match: self._fixup_dict[match.group(1)]
        return self._fixup_pattern.sub(self._fixup_repl, text)

    def _tex_fixup_url(self, url):
        return re.sub('([%#&])', r'\\\1', url)


config = Config(os.path.dirname(os.path.abspath(__file__)) + '/../config')
page = 'Mm/Bericht-Entwurf'
#page = 'Benutzer:Kahrl/Bericht'
#page = 'Benutzer:Kahrl/Sandbox/Table'

with open('report.tex', 'w') as output_file:
    with config.create_wiki_client('VroniPlag', login=False) as client:
        output_file.write(
"""\\documentclass[ngerman,final,fontsize=12pt,paper=a4,twoside,bibliography=totoc,BCOR=8mm,draft=false]{scrartcl}

\\usepackage[T1]{fontenc}
\\usepackage{babel}
\\usepackage[utf8]{inputenx}
\\usepackage[sort&compress,square]{natbib}
\\usepackage[babel]{csquotes}
\\usepackage[hyphens]{url}
\\usepackage[draft=false,final,plainpages=false,pdftex]{hyperref}
\\usepackage{eso-pic}
\\usepackage{fixltx2e}
\\usepackage{graphicx}
\\usepackage{xcolor}
\\usepackage{pdflscape}
\\usepackage{colortbl}
\\usepackage{longtable}
\\usepackage{multirow}
\\usepackage{framed}
\\usepackage{textcomp}
\\usepackage{scrtime}

\\usepackage[charter,sfscaled]{mathdesign}

%\\usepackage[spacing=true,tracking=true,kerning=true,babel]{microtype}
\\usepackage[spacing=true,kerning=true,babel]{microtype}

\\author{VroniPlag}

\\title{Bericht 20110618}
\\subtitle{Gemeinschaftliche Dokumentation von Plagiaten in der Dissertation „Amerika: das Experiment des Fortschritts. Ein Vergleich des politischen Denkens in Europa und in den USA“ von Prof.~Dr.~Margarita Mathiopoulos}
\\publishers{\\normalsize\\url{http://de.vroniplag.wikia.com/wiki/Mm}}

\\hypersetup{%
        pdfauthor={VroniPlag},%
        pdftitle={Bericht 20110618 --- Gemeinschaftliche Dokumentation von Plagiaten in der Dissertation „Amerika: das Experiment des Fortschritts. Ein Vergleich des politischen Denkens in Europa und in den USA“ von Prof.~Dr.~Margarita Mathiopoulos},%
        pdflang={en},%
        %pdfduplex={DuplexFlipLongEdge},%
        %pdfprintscaling={None},%
        %linktoc=all,%
        colorlinks,%
        linkcolor=black,%
        citecolor=green!50!black,%
        filecolor=blue,%
        urlcolor=blue,%
        linkbordercolor={1 0 0},%
        citebordercolor={0 0.5 0},%
        filebordercolor={0 0 1},%
        urlbordercolor={0 0 1},%
}

\\definecolor{shadecolor}{rgb}{0.95,0.95,0.95}

\\newenvironment{fragment}
        {\\begin{snugshade}}
        {\\end{snugshade}
                \\penalty-200
                \\vskip 0pt plus 10mm minus 5mm}
\\newenvironment{fragmentpart}[1]
        {\\indent\\textbf{#1}\\par\\penalty500\\noindent}
        {\\par}
\\newcommand{\\BackgroundPic}
        {\\put(0,0){\\parbox[b][\\paperheight]{\\paperwidth}{%
                \\vfill%
                \\centering%
                \\includegraphics[width=\\paperwidth,height=\\paperheight,%
                        keepaspectratio]{background.png}%
                \\vfill%
        }}}
\\newcommand{\hrulesep}{%
        \\nointerlineskip\\vspace{\\baselineskip}%
        \\hrule\\par%
        \\nointerlineskip\\vspace{\\baselineskip}%
}


\\setkomafont{section}{\\large}
\\addtokomafont{disposition}{\\normalfont\\boldmath\\bfseries}
\\urlstyle{rm}

\\date{\\today, \\thistime}
%\\date{19. April 2011, 17:00}

\\begin{document}

%\\AddToShipoutPicture*{\\BackgroundPic}
\\maketitle\\thispagestyle{empty}
%\\ClearShipoutPicture

\\tableofcontents

""".encode('utf-8'))

        parsed = client.parse_page(page)
        html = parsed['text']['*']
        baseurl = client.get_article_url(page)

        HTMLToLaTeX.convert_and_print(html,
                baseurl=baseurl, verbose=True, file=output_file)

        output_file.write(
"""

\\appendix
\\section{Textnachweise}

""")

        # export fragments here

        output_file.write(
"""

\\renewcommand{\\bibname}{Quellenverzeichnis}
\\bibliographystyle{dinat-custom}
\\bibliography{ab}
\\end{document}

""")
