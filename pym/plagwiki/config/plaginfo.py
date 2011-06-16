#!/usr/bin/env python
# -*- coding: utf-8 -*-

# ease eventual Python 3 transition
from __future__ import division, print_function, unicode_literals

import codecs
import ConfigParser
import re
from plagwiki.util.csvreader import csv_to_list
from plagwiki.util.pagerange import PageRange
from plagwiki.util.plagerror import PlagError


class PlagInfo(object):
    def __init__(self, name):
        self.name = name
        self.author = None
        self.title = None
        self.subtitle = None
        self.thesistype = None
        self.pages = None
        self.chapters = None
        self.totallines = None
        self.wiki = None
        self.overviewpage = None
        self.fragmentprefix = None
        self.sourcecategory = None
        self.typescategory = None
        self.barcode = None
        self.options = None
        self.pdf = None

    def verify_config(self):
        if not self.name:
            raise PlagError('Plag with no name!')
        if not self.author:
            raise PlagError('Plag '+self.name+': No author defined!')
        if not self.title:
            raise PlagError('Plag '+self.name+': No title defined!')
        if self.subtitle is None:
            raise PlagError('Plag '+self.name+': No subtitle defined!')
        if not self.thesistype:
            raise PlagError('Plag '+self.name+': No thesis type defined!')
        if self.pages is None:
            raise PlagError('Plag '+self.name+': No pages defined!')
        if self.chapters is None:
            raise PlagError('Plag '+self.name+': No chapters defined!')
        if not self.wiki:
            raise PlagError('Plag '+self.name+': No wiki defined!')
        if not self.overviewpage:
            raise PlagError('Plag '+self.name+': No overview page defined!')
        if not self.fragmentprefix:
            raise PlagError('Plag '+self.name+': No fragment prefix defined!')
        if self.pagesprefix is None:
            raise PlagError('Plag '+self.name+': No pages prefix defined!')
        if not self.fragmentcategory:
            raise PlagError('Plag '+self.name+': No fragment category defined!')
        if not self.sourcecategory:
            raise PlagError('Plag '+self.name+': No source category defined!')
        if not self.typescategory:
            raise PlagError('Plag '+self.name+': No types category defined!')
        if self.barcode is None:
            raise PlagError('Plag '+self.name+': No barcode page defined!')
        if self.options is None:
            raise PlagError('Plag '+self.name+': No options defined!')
        if self.pdf is None:
            raise PlagError('Plag '+self.name+': No PDF file name defined!')

    def _parse_pages(name, text):
        # Allowed page range inclusion settings:
        #   include - include in statistics
        #   exclude - do not include in statistics
        # Allowed page categories:
        #   frontmatter - title page, colophon, dedication, and similar
        #                 (anything in the front that is not covered by
        #                 more specific categories)
        #   toc         - table of contents
        #   foreword    - a foreword written by someone else than the author
        #                 of the work
        #   preface     - a preface written by the author of the work
        #   text        - the main text body
        #   appendix    - generic appendix page (e.g. an afterword,
        #                 data (in engineering) or detailed proofs (in math))
        #   references  - a formal bibliography section
        #   glossary    - list of terms (or acronyms) and their definitions
        #   index       - list of terms (or acronyms, or people, etc.) and
        #                 for each term a list of pages where it is used
        #   list        - anything else list-like, e.g. a list of tables or
        #                 a list of figures
        #   backmatter  - anything else in the back that is not directly
        #                 related to the main subject matter, e.g. a résumé of
        #                 the author or a colophon that is located at the end
        #   other       - no category system can be exhaustive, so here you are
        #   empty       - an empty page; this should only be used between
        #                 pages of two different types; in particular, do
        #                 not use it between chapters of the main text.
        pages = []
        allowed_include_pages = ('include', 'exclude')
        allowed_page_categories = ('frontmatter', 'toc', 'foreword', 'preface', 'text', 'appendix', 'references', 'glossary', 'index', 'list', 'backmatter', 'other', 'empty')
        for row in csv_to_list(text):
            if len(row) != 3:
                raise PlagError('Plag '+name+': row in pages field has '+len(row)+' columns, but 3 are expected: '+repr(row))
            pagerange = PageRange.parse(row[0])
            if row[1].lower() in allowed_include_pages:
                include_pages = (row[1].lower() == 'include')
            else:
                raise PlagError('Plag '+name+': invalid value \'' + row[1] + '\' for second column in pages field, must be one of: ' + ' '.join(allowed_include_pages))
            if row[2].lower() in allowed_page_categories:
                page_category = row[2].lower()
            else:
                raise PlagError('Plag '+name+': invalid value \'' + row[2] + '\' for third column in pages field, must be one of: ' + ' '.join(allowed_page_categories))
            pages.append((pagerange, include_pages, page_category))
        return tuple(pages)
    _parse_pages = staticmethod(_parse_pages)

    def _parse_chapters(name, text):
        # Allowed chapter types:
        #   chapter
        #   section
        #   TODO: define more, such as subsection, subsubsection, or part
        chapters = []
        allowed_chapter_types = ('chapter', 'section')
        for row in csv_to_list(text):
            if len(row) != 3:
                raise PlagError('Plag '+name+': row in chapters field has '+len(row)+' columns, but 3 are expected: '+repr(row))
            if row[0].lower() in allowed_chapter_types:
                chapter_type = row[0].lower()
            else:
                raise PlagError('Plag '+name+': invalid value \'' + row[0] + '\' for first column in chapters field, must be one of: ' + ' '.join(allowed_chapter_types))
            chapter_first_page = row[1]
            chapter_title = row[2]
            chapters.append((chapter_type, chapter_first_page, chapter_title))
        return tuple(chapters)
    _parse_chapters = staticmethod(_parse_chapters)

    def _parse_options(name, text):
        options = []
        for row in csv_to_list(text):
            for option in row:
                options.append(option.lower())
        return set(options)
    _parse_options = staticmethod(_parse_options)

    def new_from_config(config_parser, name, verify=True):
        info = PlagInfo(name)
        section = name
        if config_parser.has_option(section, 'author'):
            info.author = config_parser.get(section, 'author')
        if config_parser.has_option(section, 'title'):
            info.title = config_parser.get(section, 'title')
        if config_parser.has_option(section, 'subtitle'):
            info.subtitle = config_parser.get(section, 'subtitle')
        if config_parser.has_option(section, 'thesistype'):
            info.thesistype = config_parser.get(section, 'thesistype')
        if config_parser.has_option(section, 'pages'):
            info.pages = PlagInfo._parse_pages(name, config_parser.get(section, 'pages'))
        if config_parser.has_option(section, 'chapters'):
            info.chapters = PlagInfo._parse_chapters(name, config_parser.get(section, 'chapters'))
        if config_parser.has_option(section, 'totallines') and config_parser.get(section, 'totallines'):
            info.totallines = config_parser.getint(section, 'totallines')
        if config_parser.has_option(section, 'wiki'):
            info.wiki = config_parser.get(section, 'wiki')
        if config_parser.has_option(section, 'overviewpage'):
            info.overviewpage = config_parser.get(section, 'overviewpage')
        if config_parser.has_option(section, 'fragmentprefix'):
            info.fragmentprefix = config_parser.get(section, 'fragmentprefix')
        if config_parser.has_option(section, 'pagesprefix'):
            info.pagesprefix = config_parser.get(section, 'pagesprefix')
        if config_parser.has_option(section, 'fragmentcategory'):
            info.fragmentcategory = config_parser.get(section, 'fragmentcategory')
        if config_parser.has_option(section, 'sourcecategory'):
            info.sourcecategory = config_parser.get(section, 'sourcecategory')
        if config_parser.has_option(section, 'typescategory'):
            info.typescategory = config_parser.get(section, 'typescategory')
        if config_parser.has_option(section, 'barcode'):
            info.barcode = config_parser.get(section, 'barcode')
        if config_parser.has_option(section, 'options'):
            info.options = PlagInfo._parse_options(name, config_parser.get(section, 'options'))
        if config_parser.has_option(section, 'pdf'):
            info.pdf = config_parser.get(section, 'pdf')
        if verify:
            info.verify_config()
        return info
    new_from_config = staticmethod(new_from_config)

    def all_from_config(config_parser, verify=True):
        result = {}
        for section in config_parser.sections():
            result[section] = PlagInfo.new_from_config(config_parser, section)
        return result
    all_from_config = staticmethod(all_from_config)

    def all_from_file(filename, verify=True):
        config_parser = ConfigParser.SafeConfigParser()
        # use readfp instead of read as the latter silently ignores I/O errors,
        # also readfp allows us to specify utf-8
        with codecs.open(filename, 'r', 'utf8') as fp:
            config_parser.readfp(fp)
        return PlagInfo.all_from_config(config_parser, verify)
    all_from_file = staticmethod(all_from_file)
