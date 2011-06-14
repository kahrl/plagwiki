#!/usr/bin/env python
# -*- coding: utf-8 -*-

# ease eventual Python 3 transition
from __future__ import division, print_function, unicode_literals

import codecs
import ConfigParser
from plagwiki.util.plagerror import PlagError


class PlagWikiInfo(object):
    def __init__(self, name):
        self.name = name
        self.fullname = name
        self.language = None
        self.wiki = None
        self.api = None
        self.ask = None
        self.software = None

    def verify_config(self):
        if not self.name:
            raise PlagError('PlagWiki with no name!')
        if not self.fullname:
            raise PlagError('PlagWiki '+self.name+': No full name defined!')
        if not self.language:
            raise PlagError('PlagWiki '+self.name+': No language defined!')
        if not self.wiki:
            raise PlagError('PlagWiki '+self.name+': No wiki URL defined!')
        if not self.api:
            raise PlagError('PlagWiki '+self.name+': No API URL defined!')
        if not self.software:
            raise PlagError('PlagWiki '+self.name+': No wiki software defined!')
        if self.software == 'MediaWiki':
            if self.ask:
                raise PlagError('PlagWiki '+self.name+': Ask URL defined, but wiki software is MediaWiki (expected MediaWiki+SMW)!')
        elif self.software == 'MediaWiki+SMW':
            if not self.ask:
                raise PlagError('PlagWiki '+self.name+': No Ask URL defined!')
        else:
            raise PlagError('PlagWiki '+self.name+': Unknown wiki software: '+self.software+' (should be MediaWiki or MediaWiki+SMW)')

    def new_from_config(config_parser, name, verify=True):
        info = PlagWikiInfo(name)
        section = name
        if config_parser.has_option(section, 'fullname'):
            info.fullname = config_parser.get(section, 'fullname')
        if config_parser.has_option(section, 'language'):
            info.language = config_parser.get(section, 'language')
        if config_parser.has_option(section, 'wiki'):
            info.wiki = config_parser.get(section, 'wiki')
        if config_parser.has_option(section, 'api'):
            info.api = config_parser.get(section, 'api')
        if config_parser.has_option(section, 'ask'):
            info.ask = config_parser.get(section, 'ask')
        if config_parser.has_option(section, 'software'):
            info.software = config_parser.get(section, 'software')
        if verify:
            info.verify_config()
        return info
    new_from_config = staticmethod(new_from_config)

    def all_from_config(config_parser, verify=True):
        result = {}
        for section in config_parser.sections():
            result[section] = PlagWikiInfo.new_from_config(config_parser, section)
        return result
    all_from_config = staticmethod(all_from_config)

    def all_from_file(filename, verify=True):
        config_parser = ConfigParser.SafeConfigParser()
        # use readfp instead of read as the latter silently ignores I/O errors,
        # also readfp allows us to specify utf-8
        with codecs.open(filename, 'r', 'utf8') as fp:
            config_parser.readfp(fp)
        return PlagWikiInfo.all_from_config(config_parser, verify)
    all_from_file = staticmethod(all_from_file)
