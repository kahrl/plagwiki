#!/usr/bin/env python
# -*- coding: utf-8 -*-

# ease eventual Python 3 transition
from __future__ import division, print_function, unicode_literals

import os.path
from plagwiki.config.plaginfo import PlagInfo
from plagwiki.config.plagwikiinfo import PlagWikiInfo
from plagwiki.config.plagwikiuser import PlagWikiUser
from plagwiki.loaders.wikiclient import WikiClient
from plagwiki.util.plagerror import PlagError


class Config(object):
    def __init__(self, directory=None):
        self._plagwikis = {}
        self._plagwikis_canon = {}
        self._plags = {}
        self._plags_canon = {}
        self._users = {}
        self._users_canon = {}
        if directory is not None:
            self.load(directory)

    def load(self, directory):
        self._plagwikis = PlagWikiInfo.all_from_file(os.path.join(directory, 'plagwiki.conf'))
        self._plags = PlagInfo.all_from_file(os.path.join(directory, 'plags.conf'))
        self._users = PlagWikiUser.all_from_file(os.path.join(directory, 'users.conf'))
        self._canonicalize()

    def get_plagwiki(self, name):
        if name in self._plagwikis:
            return self._plagwikis[name]
        elif name in self._plagwikis_canon:
            return self._plagwikis[self._plagwikis_canon[name]]
        else:
            raise PlagError('No such plagwiki: ' + name)

    def has_plagwiki(self, name):
        return (name in self._plagwikis) or (name in self._plagwikis_canon)

    def get_all_plagwikis(self):
        return self._plagwikis.keys()

    def get_plag(self, name):
        if name in self._plags:
            return self._plags[name]
        elif name in self._plags_canon:
            return self._plags[self._plags_canon[name]]
        else:
            raise PlagError('No such plag: ' + name)

    def has_plag(self, name):
        return (name in self._plags) or (name in self._plags_canon)

    def get_all_plags(self):
        return self._plags.keys()

    def get_user(self, name):
        if name in self._users:
            return self._users[name]
        elif name in self._users_canon:
            return self._users[self._users_canon[name]]
        else:
            raise PlagError('No such user: ' + name)

    def has_user(self, name):
        return (name in self._users) or (name in self._users_canon)

    def get_all_users(self):
        return self._users.keys()

    def create_wiki_client(self, name, login=True):
        wikiinfo = self.get_plagwiki(name)
        client = WikiClient(wikiinfo.api)
        if wikiinfo.software == 'MediaWiki+SMW':
            client.enable_semantic_mediawiki(wikiinfo.ask)
        if login:
            self.login_wiki_client(name, client)
        return client

    def login_wiki_client(self, name, client):
        if self.has_user(name):
            userinfo = self.get_user(name)
            if userinfo.username and userinfo.password:
                client.login(userinfo.username, userinfo.password)

    def create_plag_client(self, name, login=True):
        plaginfo = self.get_plag(name)
        return self.create_wiki_client(plaginfo.wiki)

    def login_plag_client(self, name, login=True):
        plaginfo = self.get_plag(name)
        self.login_wiki_client(plaginfo.wiki)

    def _canonicalize(self):
        self._plagwikis_canon = self._canonicalize_dict(self._plagwikis)
        self._plags_canon = self._canonicalize_dict(self._plags)
        self._users_canon = self._canonicalize_dict(self._users)

    def _canonicalize_dict(self, d):
        canon = {}
        for key in d:
            canon[key.lower()] = key
        return canon

