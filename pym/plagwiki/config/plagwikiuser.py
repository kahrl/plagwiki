#!/usr/bin/env python
# -*- coding: utf-8 -*-

# ease eventual Python 3 transition
from __future__ import division, print_function, unicode_literals

import codecs
import ConfigParser
from plagwiki.util.plagerror import PlagError


class PlagWikiUser(object):
    def __init__(self, name):
        self.name = name
        self.username = None
        self.password = None
        self.emergencypage = None
        self.emergencyvar = None

    def verify_config(self):
        if not self.name:
            raise PlagError('PlagWikiUser with no name!')
        if self.emergencypage and not self.emergencyvar:
            raise PlagError('PlagWikiUser '+self.name+': emergencypage defined, but no emergencyvar!')
        if self.emergencyvar and not self.emergencypage:
            raise PlagError('PlagWikiUser '+self.name+': emergencyvar defined, but no emergencypage!')

    def new_from_config(config_parser, name, verify=True):
        user = PlagWikiUser(name)
        section = name
        if config_parser.has_option(section, 'username'):
            user.username = config_parser.get(section, 'username')
        if config_parser.has_option(section, 'password'):
            user.password = config_parser.get(section, 'password')
        if config_parser.has_option(section, 'emergencypage'):
            user.emergencypage = config_parser.get(section, 'emergencypage')
        if config_parser.has_option(section, 'emergencyvar'):
            user.emergencyvar = config_parser.get(section, 'emergencyvar')
        if verify:
            user.verify_config()
        return user
    new_from_config = staticmethod(new_from_config)

    def all_from_config(config_parser, verify=True):
        result = {}
        for section in config_parser.sections():
            result[section] = PlagWikiUser.new_from_config(config_parser, section)
        return result
    all_from_config = staticmethod(all_from_config)

    def all_from_file(filename, verify=True):
        config_parser = ConfigParser.SafeConfigParser()
        # use readfp instead of read as the latter silently ignores I/O errors,
        # also readfp allows us to specify utf-8
        with codecs.open(filename, 'r', 'utf8') as fp:
            config_parser.readfp(fp)
        return PlagWikiUser.all_from_config(config_parser, verify)
    all_from_file = staticmethod(all_from_file)
