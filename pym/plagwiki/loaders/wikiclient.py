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
    ### Constructor and support for 'with' statements ###

    def __init__(self, api):
        self._api = api
        self._ask = None
        self._curl = pycurl.Curl()
        self._curl.setopt(pycurl.VERBOSE, 0)
        self._curl.setopt(pycurl.HEADER, 0)
        self._curl.setopt(pycurl.NOPROGRESS, 1)
        self._curl.setopt(pycurl.FOLLOWLOCATION, 1)
        self._curl.setopt(pycurl.MAXREDIRS, 5)
        self._curl.setopt(pycurl.USERAGENT, self._to_utf8(DEFAULT_USERAGENT))
        self._curl.setopt(pycurl.COOKIEFILE, self._to_utf8(''))
        self._useragent = DEFAULT_USERAGENT
        self._logged_in = False
        self.clear_cached_info()

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.logout()

    ### Configuration ###

    def get_api_url(self):
        return self._api

    def enable_semantic_mediawiki(self, ask):
        self._ask = ask

    def has_semantic_mediawiki(self):
        return self._ask is not None

    def get_ask_url(self):
        return self._ask

    def get_user_agent(self):
        return self._useragent

    def set_user_agent(self, user_agent):
        self._useragent = unicode(user_agent)
        self._curl.setopt(pycurl.USERAGENT, self._to_utf8(self._useragent))

    ### Login and logout ###

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
            if r_login['login']['result'] == 'WrongPluginPass':
                raise WikiError('Login failed, wrong password!')
            if r_login['login']['result'] != 'Success':
                raise LookupError()
        except(LookupError,TypeError):
            raise WikiError('MediaWiki login request failed,' +
                    ' here is the full response: ' +
                    "\n" + pprint.pformat(r_login))
        self._logged_in = True
        self.clear_cached_info()

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
                self.clear_cached_info()

    def is_logged_in(self):
        return self._logged_in

    ### Initialization ###

    def request_siteinfo(self):
        if not self.has_siteinfo():
            r_siteinfo = self._query_api(action='query', meta='siteinfo',
                    siprop='general|namespaces|namespacealiases')
            try:
                if not r_siteinfo['query']['general']:
                    raise LookupError()
                if not r_siteinfo['query']['namespaces']:
                    raise LookupError()
                if not r_siteinfo['query']['namespacealiases']:
                    raise LookupError()
                self._siteinfo = r_siteinfo['query']
                # Get list of namespaces and namespace aliases
                self._siteinfo_ns = {}
                self._siteinfo_ns_normalized = {}
                for ns in self._siteinfo['namespaces'].values():
                    ns_id = int(ns['id'])
                    self._siteinfo_ns[int(ns_id)] = int(ns_id)
                    self._siteinfo_ns[ns['*'].lower()] = int(ns_id)
                    if 'canonical' in ns:
                        self._siteinfo_ns[ns['canonical'].lower()] = int(ns_id)
                    self._siteinfo_ns_normalized[ns_id] = ns['*']
                for ns in self._siteinfo['namespacealiases']:
                    ns_id = int(ns['id'])
                    self._siteinfo_ns[ns['*'].lower()] = ns_id
                    if not ns_id in self._siteinfo_ns_normalized:
                        # should not happen
                        self._siteinfo_ns_normalized[ns_id] = ns['*']
            except(LookupError,TypeError):
                raise WikiError('MediaWiki siteinfo request failed,' +
                    ' here is the full response: ' +
                    "\n" + pprint.pformat(r_siteinfo))

    def has_siteinfo(self):
        return bool(self._siteinfo)

    def get_siteinfo(self):
        return self._siteinfo

    def request_edittoken(self):
        if not self.has_edittoken():
            self.request_siteinfo
            r_edittoken = self._query_api(action='query', prop='info',
                    intoken='edit', titles='DummyEditTokenPage')
            try:
                self._edittoken = unicode(
                        r_edittoken['query']['pages'].values()[0]['edittoken'])
            except(LookupError,TypeError):
                raise WikiError('MediaWiki edit token request failed,' +
                    ' here is the full response: ' +
                    "\n" + pprint.pformat(r_edittoken))

    def has_edittoken(self):
        return bool(self._edittoken)

    def get_edittoken(self):
        return self._edittoken

    def clear_cached_info(self):
        self._siteinfo = None
        self._siteinfo_ns = None
        self._siteinfo_ns_normalized = None
        self._edittoken = None

    ### Purging wiki pages ###

    def purge(self, title):
        r_purge = self._query_api(action='purge', titles=title)
        # TODO verify success

    def purge_multi(self, titles):
        titles_joined = '|'.join(titles)
        r_purge = self._query_api(action='purge', titles=titles_joined)
        # TODO verify success

    ### Editing and uploading ###

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

    ### Internal methods (low-level query methods) ###

    def _query_prefix_list(self, prefix, redirects=None, namespace=None):
        """Query a list of pages with a given prefix.

        prefix is the prefix of the page names that are searched. It includes
        or excludes the namespace, depending on how the namespace parameter
        is set (see below).

        redirects may be None, False or True. If redirects is None, the
        query returns both redirects and non-redirects. If redirects is
        False, the query returns only non-redirects. If redirects is True,
        only redirects are returned. The default is None.

        namespace defines which namespace is searched. The default is None,
        which means the namespace is inferred from the prefix parameter.
        Otherwise, the prefix parameter should not include a namespace prefix
        and namespace may a namespace number or a namespace name (custom and
        localized names are allowed, as well as namespace aliases).

        Returns the API result. This method automatically resumes the query
        if the result limit is exceeded.

        Precondition: request_siteinfo() must have been called before.

        """
        if namespace is None:
            nsnumber, prefix = self._split_name(prefix)
        else:
            nsnumber = self._namespace_to_number(namespace)
        kw = {'action':'query', 'list':'allpages',
                'aplimit':'max', 'apprefix':prefix, 'apnamespace':nsnumber}
        if redirects is not None:
            if redirects:
                kw['apfilterredir'] = 'redirects'
            else:
                kw['apfilterredir'] = 'nonredirects'
        r_query = self._query_api(**kw)
        try:
            # Continue query if result is incomplete.
            while 'query-continue' in r_query:
                kw['apfrom'] = r_query['query-continue']['allpages']['apfrom']
                r_query2 = self._query_api(**kw)
                r_query = self._merge_recursive(r_query, r_query2)
            if r_query['query']['allpages'] is None:
                raise LookupError()
            return r_query
        except(LookupError,TypeError):
            raise WikiError('MediaWiki prefix query failed,' +
                ' here is the full response: ' +
                "\n" + pprint.pformat(r_query))

    def _query_category_members(self, category, namespace=None, with_sortkey=False, with_timestamp=False):
        """Query a list of pages in the given category.

        category is the name of the category, with or without the
        'Category:' namespace prefix.

        namespace defines which namespaces are searched. The default is None,
        which means that the results are not limited by namespace. Otherwise,
        namespace may a namespace number or a namespace name (custom and
        localized names are allowed, as well as namespace aliases), and
        specifies which namespace the results should be limited to.

        If with_sortkey is set to True, the results include the sort key
        of each category member.

        If with_timestamp is set to True, the time and date articles were
        added to the category are included in the results.

        Returns the API result. This method automatically resumes the query
        if the result limit is exceeded.

        Precondition: request_siteinfo() must have been called before.

        """
        nsnumber, rest = self._split_name(category)
        if nsnumber == 0:  # happens if namespace is omitted
            nsnumber = self._namespace_to_number('Category')
        category = self._combine_name(nsnumber, rest)
        kw = {'action':'query', 'list':'categorymembers',
                'cmlimit':'max', 'cmtitle':category, 'cmprop':'ids|title'}
        if namespace is not None:
            kw['cmnamespace'] = self._namespace_to_number(namespace)
        if with_sortkey:
            kw['cmprop'] += '|sortkey'
        if with_timestamp:
            kw['cmprop'] += '|timestamp'

        r_query = self._query_api(**kw)
        try:
            while 'query-continue' in r_query:
                kw['cmcontinue'] = r_query['query-continue']['categorymembers']['cmcontinue']
                r_query2 = self._query_api(**kw)
                r_query = self._merge_recursive(r_query, r_query2)
            if r_query['query']['categorymembers'] is None:
                raise LookupError()
            return r_query
        except(LookupError,TypeError):
            raise WikiError('MediaWiki categorymembers query failed,' +
                ' here is the full response: ' +
                "\n" + pprint.pformat(r_query))

    def _query_entries(self, ids_or_titles, using_titles):
        """Retrieve page data given a list of page IDs or page titles.

        ids_or_titles is a sequence of integers or strings, depending on
        the value of using_titles.

        If using_titles is True, ids_or_titles must be a sequence of strings
        that are interpreted as page titles. If using_titles is False,
        ids_or_titles must be a sequence of integers that are interpreted
        as page IDs.

        Returns the API result. This method automatically resumes the query
        if the result limit is exceeded.

        """
        chunk_size = 50
        r_total = {}
        for chunk_pos in range(0, len(ids_or_titles), chunk_size):
            chunk = ids_or_titles[chunk_pos : chunk_pos + chunk_size]
            chunk_piped = '|'.join(unicode(x) for x in chunk)
            kw = {'action':'query', 'prop':'info|revisions|categories',
                    'rvprop':'content', 'cllimit':'300'}
            if using_titles:
                kw['titles'] = chunk_piped
            else:
                kw['pageids'] = chunk_piped
            r_query = self._query_api(**kw)
            try:
                while 'query-continue' in r_query:
                    kw['clcontinue'] = r_query['query-continue']['categories']['clcontinue']
                    r_query2 = self._query_api(**kw)
                    r_query = self._merge_recursive(r_query, r_query2)
                if r_query['query']['pages'] is None:
                    raise LookupError()
                # Hacky fix for a minor problem.
                # If we had to repeat the query to get all categories,
                # _merge_recursive concatenated the revisions list for each
                # page (so we get the same result repeated n times, where n
                # is the number of queries we had to do). _merge_recursive's
                # concatenating behavior is good, since it allows us to
                # combine the category lists from multiple queries. But it
                # causes the stated problem with the revisions field.
                for page in r_query['query']['pages'].values():
                    page['revisions'] = page['revisions'][0:1]
                # Combine all query results into a total result.
                r_total = self._merge_recursive(r_total, r_query)
            except(LookupError,TypeError):
                raise WikiError('MediaWiki pages query failed,' +
                    ' here is the full response: ' +
                    "\n" + pprint.pformat(r_query))
        return r_total

    ### Name and namespace helper methods ###

    def _normalize_name(self, name):
        nsnumber, rest = self._split_name(name)
        return self._combine_name(nsnumber, rest)

    def _combine_name(self, nsnumber, rest):
        # TODO: normalize special page names?
        nsname = self._normalize_namespace(nsnumber)
        rest = rest.replace('_', ' ')
        rest = rest[0:1].upper() + rest[1:]  # capitalize only first
        if nsname:
            return nsname + ':' + rest
        else:
            return rest

    def _split_name(self, name):
        parts = name.split(':', 1)
        assert len(parts) >= 1
        assert len(parts) <= 2
        if len(parts) == 2:
            nsnumber = self._namespace_to_number(parts[0], False)
            if nsnumber is not None:
                return (nsnumber, parts[1])
        return (0, name)  # article namespace

    def _normalize_namespace(self, ns):
        assert self.has_siteinfo()
        nsnumber = self._namespace_to_number(ns)
        try:
            return self._siteinfo_ns_normalized[nsnumber]
        except(LookupError):
            raise WikiError('No such namespace: ' + unicode(ns))

    def _namespace_to_number(self, ns, raise_on_error=True):
        assert self.has_siteinfo()
        if ns in self._siteinfo_ns:  # also handles numeric ns arguments
            return self._siteinfo_ns[ns]
        else:
            # assume ns is a string and normalize it
            ns_normalized = unicode(ns).lower().replace('_', ' ')
            if ns_normalized in self._siteinfo_ns:
                return self._siteinfo_ns[ns_normalized]
            elif raise_on_error:
                raise WikiError('No such namespace: ' + unicode(ns))
            else:
                return None

    ### Internal methods (direct MediaWiki API access) ###

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
        if __debug__:
            print("Request:")
            pprint.pprint(kw)
            print()
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
            if __debug__:
                print("Result:")
                pprint.pprint(json.loads(response_uni))
                print()
            return json.loads(response_uni)
        except(ValueError) as err:
            raise WikiError('Error while accessing ' + self._api + ': ' +
                             unicode(err) + "\n\n" +
                             "Response was:\n" +
                             self._truncate_text(response_uni, 500))

    ### Utilities ###

    def _to_utf8(self, value):
        return unicode(value).encode('utf-8')

    def _truncate_text(self, text, limit):
        if len(text) <= limit:
            return text
        elif limit < 3:
            return '.' * limit
        else:
            return text[0:(limit-3)] + '...'

    def _merge_recursive(self, r1, r2, toplevel=True):
        if isinstance(r1, dict) and isinstance(r2, dict):
            r = {}
            for key in r1:
                # special case query-continue in the topmost level:
                # it is always dropped from r1
                if not toplevel or key != 'query-continue':
                    r[key] = r1[key]
            for key in r2:
                if key in r:
                    r[key] = self._merge_recursive(r[key], r2[key], False)
                else:
                    r[key] = r2[key]
            return r
        elif isinstance(r1, tuple) and isinstance(r2, tuple):
            return r1+r2
        elif isinstance(r1, list) and isinstance(r2, list):
            return r1+r2
        else:
            return r2
