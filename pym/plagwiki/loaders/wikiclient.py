#!/usr/bin/env python
# -*- coding: utf-8 -*-

# ease eventual Python 3 transition
from __future__ import division, print_function, unicode_literals

import hashlib
import io
import json
import os
import pprint
import pycurl
import sys

from plagwiki.loaders.wikierror import WikiError


DEFAULT_USERAGENT = 'plagwiki/0.1a'

class WikiClient(object):
    def __init__(self, api, ask, mainpage):
        self._api = api
        self._ask = ask
        self._mainpage = mainpage
        self._curl = pycurl.Curl()
        self._curl.setopt(pycurl.VERBOSE, 0)
        self._curl.setopt(pycurl.HEADER, 0)
        self._curl.setopt(pycurl.NOPROGRESS, 1)
        self._curl.setopt(pycurl.FOLLOWLOCATION, 1)
        self._curl.setopt(pycurl.MAXREDIRS, 5)
        self._curl.setopt(pycurl.USERAGENT, self._to_utf8(DEFAULT_USERAGENT))
        self._curl.setopt(pycurl.COOKIEFILE, self._to_utf8(''))
        self._useragent = DEFAULT_USERAGENT
        self._edittoken = ''
        self._logged_in = False

    def __del__(self):
        self.logout()

    def get_user_agent(self):
        return self._useragent

    def set_user_agent(self, user_agent):
        self._useragent = unicode(user_agent)
        self._curl.setopt(pycurl.USERAGENT, self._to_utf8(self._useragent))

    def login(self, username, password):
        r_prelogin = self._query_api(action='login',
                lgname=username, lgpassword=password)
        try:
            if r_prelogin['login']['result'] == 'WrongPass':
                raise WikiError('Login failed, wrong password!')
            if r_prelogin['login']['result'] != 'NeedToken':
                raise LookupError()
            prelogin_token = r_prelogin['login']['token']
        except(LookupError,TypeError):
            raise WikiError('MediaWiki pre-login request failed (expected' +
                    ' NeedToken), here is the full response: ' +
                    "\n" + pprint.pformat(r_prelogin))
        r_login = self._query_api(action='login',
                lgname=username, lgpassword=password,
                lgtoken=prelogin_token)
        try:
            if r_login['login']['result'] == 'WrongPass':
                raise WikiError('Login failed, wrong password!')
            if r_login['login']['result'] != 'Success':
                raise LookupError()
        except(LookupError,TypeError):
            raise WikiError('MediaWiki login request failed,' +
                    ' here is the full response: ' +
                    "\n" + pprint.pformat(r_login))
        self._logged_in = True
        self._edittoken = ''

    def logout(self):
        if self._logged_in:
            try:
                self._query_api(action='logout')
            except(WikiError) as err:
                print(unicode(err), file=sys.stderr)
                print('Warning: MediaWiki logout request failed!',
                        file=sys.stderr)
            else:
                self._logged_in = False
                self._edittoken = ''

    def is_logged_in(self):
        return self._logged_in

    def purge(self, title):
        r_purge = self._query_api(action='purge', titles=title)
        # TODO verify success

    def purge_multi(self, titles):
        titles_joined = '|'.join(titles)
        r_purge = self._query_api(action='purge', titles=titles_joined)
        # TODO verify success

    def request_edittoken(self):
        if not self.has_edittoken():
            r_edittoken = self._query_api(action='query', prop='info',
                    intoken='edit', titles=self._mainpage)
            try:
                self._edittoken = unicode(
                        r_edittoken['query']['pages'].values()[0]['edittoken'])
            except(LookupError,TypeError):
                raise WikiError('MediaWiki edit token request failed,' +
                    ' here is the full response: ' +
                    "\n" + pprint.pformat(r_edittoken))

    def has_edittoken(self):
        return self._edittoken != ''

    def edit(self, title, text, summary=None, minor=True, bot=True):
        self.request_edittoken()
        text = unicode(text)
        md5 = hashlib.md5(self._to_utf8(text)).hexdigest()
        r_edit = self._query_api(action = 'edit',
                title = title, text = text, md5 = md5, summary = summary,
                token = self._edittoken, minor = bool(minor), bot = bool(bot),
                watchlist = 'nochange')
        try:
            if r_edit['edit']['result'] != 'Success':
                raise LookupError()
        except(LookupError,TypeError):
            raise WikiError('MediaWiki edit request failed,' +
                    ' here is the full response: ' +
                    "\n" + pprint.pformat(r_edit))

    def upload(self, local_filename, remote_filename=None, text=None, summary=None):
        self.request_edittoken()
        if remote_filename is None:
            remote_filename = os.path.basename(local_filename)
        r_upload = self._query_api(action='upload', filename=remote_filename,
                ignorewarnings='', token=self._edittoken,
                text=text, comment=summary,
                file=(local_filename, 'file', 'application/octet-stream'))
        try:
            if r_upload['upload']['result'] != 'Success':
                raise LookupError()
        except(LookupError,TypeError):
            raise WikiError('MediaWiki upload request failed,' +
                ' here is the full response: ' +
                "\n" + pprint.pformat(r_upload))

    def _query_api(self, **kw):
        """Perform a raw MediaWiki API request.

        Each keyword argument is passed as an HTTP POST parameter
        to the Wiki's api.php. The one exception is 'format', which
        is ignored and always set to 'json'. Finally, the JSON returned
        by the server is parsed with simplejson and then returned.

        For example, to get the first 500 page titles:
            wc._query_api(action='query', list='allpages', aplimit=500)

        Do not urlencode the parameters as this function already does that.

        Performing file uploads:
        Argument values may be tuples (instead of strings or integers
        as in the above example). In that case, the tuple must contain
        three elements: (value, is_file, contenttype)
        value:        The file name (if is_file is 'file') or value (if
                      is_file is 'string'). Need not be a string if is_file
                      is 'string', as it is passed through unicode() first.
        is_file:      Whether value is the name of a file to be uploaded
                      ('file') or should be passed as-is ('string').
        contenttype:  The MIME type. This may be set to None if not needed.
        Non-tuple argument values are equivalent to (value, 'string', None).

        For example, to upload a file Asdf.png and call it Ghjk.png on
        the server:
            wc._query_api(action='upload', filename='Ghjk.png',
                          ignorewarnings='', token=edittoken,
                          file=('Asdf.png', 'file', 'image/png'))

        """

        # pycurl expects form contents in the following format:
        # [(argname, (pycurl.FORM_xxx, value, pycurl.FORM_xxx, value, ...)),
        #  (argname, (pycurl.FORM_xxx, value, pycurl.FORM_xxx, value, ...)),
        #  ...]
        # This method does not support pycurl.FORM_FILENAME.
        # Note that pycurl currently (May 2011) doesn't support unicode.
        kw['format'] = 'json'
        form = []
        for argname in sorted(kw):
            argvalue = kw[argname]
            argname = unicode(argname)

            if argvalue is None:
                continue
            if not isinstance(argvalue, (list, tuple)):
                argvalue = (argvalue, 'string', None)
            argvalue = tuple(argvalue)
            if len(argvalue) == 1:
                argvalue = (argvalue[0], 'string', None)
            elif len(argvalue) == 2:
                argvalue = (argvalue[0], argvalue[1], None)
            elif len(argvalue) != 3:
                raise ValueError('keyword argument is not a 3-tuple: ' +
                                 unicode(argvalue))

            value, is_file, contenttype = argvalue
            if isinstance(value, bool):
                value = unicode(value).lower()
            if is_file != 'file' and is_file != 'string':
                raise ValueError('second entry of keyword argument must be' +
                                 '\'file\' or \'string\': ' + unicode(is_file))
            if is_file == 'file':
                formfield = [pycurl.FORM_FILE, self._to_utf8(value)]
            else:
                formfield = [pycurl.FORM_CONTENTS, self._to_utf8(value)]
            if contenttype is not None:
                formfield += [pycurl.FORM_CONTENTTYPE, self._to_utf8(contenttype)]
            form.append((self._to_utf8(argname), tuple(formfield)))

        buffer = io.BytesIO()
        self._curl.setopt(pycurl.URL, self._to_utf8(self._api))
        self._curl.setopt(pycurl.HTTPPOST, form)
        self._curl.setopt(pycurl.WRITEFUNCTION, buffer.write)

        try:
            self._curl.perform()
        except(pycurl.error) as err:
            raise WikiError('Error while accessing ' + self._api + ': ' +
                            self._curl.errstr())

        response_code = self._curl.getinfo(pycurl.RESPONSE_CODE)
        if not (response_code >= 200 and response_code <= 299):
            raise WikiError('Error while accessing ' + self._api + ': ' +
                            "Response was HTTP " + unicode(response_code))

        response_uni = buffer.getvalue().decode('utf-8')
        try:
            return json.loads(response_uni)
        except(ValueError) as err:
            raise WikiError('Error while accessing ' + self._api + ': ' +
                             unicode(err) + "\n\n" +
                             "Response was:\n" +
                             self._truncate_text(response_uni, 500))

    def _to_utf8(self, value):
        return unicode(value).encode('utf-8')

    def _truncate_text(self, text, limit):
        if len(text) <= limit:
            return text
        elif limit < 3:
            return '.' * limit
        else:
            return text[0:(limit-3)] + '...'

