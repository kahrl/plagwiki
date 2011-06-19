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
    def __init__(self):
        HTMLParser.HTMLParser.__init__(self)
        self.__empty_tags = set(('area', 'base', 'basefont', 'br',
                'col', 'frame', 'hr', 'img', 'input', 'isindex',
                'link', 'meta', 'param'))
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
        if tag in self.__empty_tags:
            self.__handle_endtag_or_emptytag(tag)

    def handle_endtag(self, tag):
        if tag in self.__empty_tags:
            raise RuntimeError('Tag '+tag+' can\'t be closed using </'+tag+'>, use <'+tag+' /> instead')
        self.__handle_endtag_or_emptytag(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.__empty_tags:
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
        if verbose:
            pprint.pprint(self._structure)

    def get_output(self):
        return self._output.getvalue()

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
        # more context.table_xxx variables are set when <table> is processed
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
                context.out.write(' ')
            pass
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
                if context.in_cite_ref:
                    # This links to a reference
                    context.name_cite_ref = re.sub('^#', '', attrs['href'])
                elif context.in_references and attrs['href'][0:1] == '#' and \
                        children == ['\u2191']:
                    # This is a backlink from a reference
                    pass
                else:
                    # This is a normal link
                    url = urlparse.urljoin(self._baseurl, attrs['href'])
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
        elif tag == 'hr':
            context.out.write('\hrulesep{}')

        elif tag == 'table':
            context2 = copy(context)
            context2.out = io.StringIO()  # temp redirect to /dev/null
            context2.table = dict()
            context2.table_rowtag = None
            context2.table_caption = ''
            context2.table_caption_below = False
            context2.table_x = 0
            context2.table_y = 0
            context2.table_xmax = 0
            context2.table_ymax = 0
            self._process_list(children, context2)
            context.out.write(r'\begin{table}[htbp]' + '\n')
            context.out.write(r'\centering' + '\n')
            if context2.table_caption and not context2.table_caption_below:
                context.out.write(r'\caption{' + context2.table_caption + '}\n')
            context.out.write(r'\begin{tabular}{')
            for x in range(1, context2.table_xmax+1):
                context.out.write('l')
            context.out.write('}\n')
            for y in range(1, context2.table_ymax+1):
                for x in range(1, context2.table_xmax+1):
                    if (x,y) in context2.table:
                        context.out.write(context2.table[(x,y)])
                context.out.write(r'\\'+'\n')
            context.out.write(r'\end{tabular}' + '\n')
            if context2.table_caption and context2.table_caption_below:
                context.out.write('\\caption{' + context2.table_caption + '}\n')
            context.out.write(r'\end{table}' + '\n')
        elif tag == 'caption':
            if context.table is None:
                raise RuntimeError(tag + ' encountered outside table')
            context.out.seek(0)
            context.out.truncate()
            self._process_list(children, context)
            context.table_caption = context.out.getvalue()
            context.table_caption_below = bool(context.table) # is it nonempty?
        elif tag == 'tr' or tag == 'thead' or tag == 'tfoot':
            if context.table is None:
                raise RuntimeError(tag + ' encountered outside table')
            context.table_rowtag = tag
            context.table_x = 0
            context.table_y += 1
            self._process_list(children, context)
            context.table_rowtag = None
        elif tag == 'td' or tag == 'th':
            # TODO: use alignment from style, halign and valign
            if context.table is None:
                raise RuntimeError(tag + ' encountered outside table')
            if context.table_rowtag is None:
                raise RuntimeError(tag + ' encountered outside table row')
            context.table_x += 1
            while (context.table_x, context.table_y) in context.table:
                context.table_x += 1
            context.table_xmax = max(context.table_x, context.table_xmax)
            context.out.seek(0)
            context.out.truncate()
            self._process_list(children, context)
            main_cell_contents = context.out.getvalue()
            above_cell_contents = ''
            is_header_cell = (tag == 'th' or context.table_rowtag == 'thead' or context.table_rowtag == 'tfoot')
            colspan = rowspan = 1
            if 'colspan' in attrs:
                colspan = max(int(attrs['colspan']), 1)
            if 'rowspan' in attrs:
                rowspan = max(int(attrs['rowspan']), 1)
            if rowspan != 1:
                main_cell_contents = '\\multirow{-' + unicode(rowspan) + '}{*}{' + main_cell_contents + '}'
                above_cell_contents = '~'
            if is_header_cell:
                main_cell_contents = '\\multicolumn{' + unicode(colspan) + '}{c}{\\textbf{' + main_cell_contents + '}}'
                above_cell_contents = '\\multicolumn{' + unicode(colspan) + '}{c}{' + above_cell_contents + '}'
            elif colspan != 1:
                main_cell_contents = '\\multicolumn{' + unicode(colspan) + '}{l}{' + main_cell_contents + '}'
                above_cell_contents = '\\multicolumn{' + unicode(colspan) + '}{l}{' + above_cell_contents + '}'
            for x in range(context.table_x, context.table_x + colspan):
                for y in range(context.table_y, context.table_y + rowspan):
                    if x == context.table_x:
                        cellprefix = '' if x == 1 else '& '
                        if y == context.table_y + rowspan - 1:
                            context.table[(x, y)] = cellprefix + main_cell_contents
                        else:
                            context.table[(x, y)] = cellprefix + above_cell_contents
                    else:
                        context.table[(x, y)] = ''
            context.table_xmax = max(context.table_xmax, context.table_x + colspan - 1)
            context.table_ymax = max(context.table_ymax, context.table_y + rowspan - 1)
            pprint.pprint(context.table)
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
        return re.sub('([%#])', r'\\\1', url)


config = Config(os.path.dirname(os.path.abspath(__file__)) + '/../config')
page = 'Benutzer:Kahrl/Bericht'

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
