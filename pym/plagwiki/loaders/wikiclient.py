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
import re
import sys

from plagwiki.loaders.emergencyerror import EmergencyError
from plagwiki.loaders.wikierror import WikiError


DEFAULT_USERAGENT = 'plagwiki/0.1a'

class WikiClient(object):
    """Manages a session with a wiki server.

    Provides methods for getting text and metadata of pages, querying
    lists of pages with a given prefix, querying the list of members
    of a category, editing a page, uploading files, logging in and out,
    and more.

    Currently, this class supports MediaWiki servers using the API.
    Support for the Semantic MediaWiki extension (including arbitrary
    SMW queries) is planned for the future.

    Almost all methods (except the most simplest getters) may raise
    exceptions, in particular those that access the API. In case of
    problems with the API or the wiki itself, a WikiError is raised.

    """

    ### Constructor and support for 'with' statements ###

    def __init__(self, api):
        """Constructor.

        api must be a fully qualified URL to the MediaWiki API.
        For example, api = 'http://de.guttenplag.wikia.com/api.php'.

        The constructor does not communicate with the API, neither
        for logging in (see login() for that), for querying site information
        (see request_siteinfo() for that), nor for requesting tokens (see
        request_edittoken() for that). Note that these operations, apart
        from logging in, are performed automatically as soon as any method
        requires them.

        """
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
        self._emergencypage = None
        self._emergencyvar = None
        self.clear_cached_info()

    def __enter__(self):
        """Called when entering a with statement.

        This returns self, so you can say:
            with WikiClient('http://.../api.php') as c:
                do something with c
        """
        return self

    def __exit__(self, type, value, traceback):
        """Called when exiting a with statement. This calls the logout() method."""
        self.logout()

    ### Configuration ###

    def get_api_url(self):
        """Return the URL to api.php."""
        return self._api

    def enable_semantic_mediawiki(self, ask):
        """Enable Semantic MediaWiki queries.
        
        SMW queries are disabled by default. (Enabling them has no real
        effect at the moment, as SMW queries are not implemented.)

        ask must be the full URL to Special:Ask (possibly localized).
        For example, set ask to
        'http://de.guttenplag.wikia.com/wiki/Spezial:Semantische_Suche'.

        """
        self._ask = ask

    def has_semantic_mediawiki(self):
        """Return true if Semantic MediaWiki queries have been enabled."""
        return self._ask is not None

    def get_ask_url(self):
        """Return the URL to Special:Ask, or None if Semantic MediaWiki
        queries have not been enabled."""
        return self._ask

    def get_user_agent(self):
        """Return the user agent string."""
        return self._useragent

    def set_user_agent(self, user_agent):
        """Change the user agent string."""
        self._useragent = unicode(user_agent)
        self._curl.setopt(pycurl.USERAGENT, self._to_utf8(self._useragent))

    ### Login and logout ###

    def login(self, username, password):
        """Log into the API with a wiki account.

        username and password are used as credentials. Beware that the
        password is transmitted in plain text if HTTPS is not employed.

        Logging in is only required for certain features such as editing
        protected pages, deleting pages or blocking users. (All of these
        only work if the account has sufficient permissions, of course.)
        You also have to log in to change user settings or watchlist.
        Finally, depending on the wiki configuration, logging in may
        increase or remove the API limits and thereby increase throughput.

        """
        r_prelogin = self._query_api(action='login',
                lgname=username, lgpassword=password)
        try:
            if r_prelogin['login']['result'] == 'WrongPass':
                raise WikiError('Login failed, wrong password!')
            if r_prelogin['login']['result'] != 'NeedToken':
                raise LookupError()
            prelogin_token = r_prelogin['login']['token']
        except(LookupError,TypeError):
            raise WikiError('wiki pre-login request failed (expected' +
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

    def logout(self, force=False):
        """Log out of the API. This does nothing if not logged in.

        Set force to True to send a log out request even if the client
        thinks it is already logged out.

        """
        if self._logged_in or force:
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
        """Return True if the client thinks it is logged in.

        This may erroneously return True in case the login session
        has been idle for a while and timed out by the server.
        TODO: write a method that asks meta=userinfo if we're still logged in.

        """
        return self._logged_in

    ### Emergency halt for bots ###

    def set_emergency_page(self, page, var):
        """Set the bot's emergency page for check_emergency().

        page is the emergency page name, usually a subpage of the user page.
        var is the name of the emergency variable.

        See also check_emergency().

        """
        self._emergencypage = page
        self._emergencyvar = var

    def check_emergency(self):
        """Download the wikitext of the defined emergency page, and raise
        an EmergencyError if the emergency variable has been activated.

        Assume that PAGE, VAR are the parameters to the most recent call to
        set_emergency_page(). If either is None or set_emergency_page() has
        never been called, a warning message is printed to stderr and the
        method returns. Otherwise the wikitext of PAGE is retrieved and
        scanned for an occurrence of <VAR>=<VALUE>. If VALUE is anything
        else than zero an EmergencyError is raised. Note that text inside
        <!-- comments --> is stripped before looking for the variable.

        Use this facilty in automated bots and protect the emergency page
        so that other administrators can halt your bot.

        """
        page = self._emergencypage
        var = self._emergencyvar
        if page is None:
            print("Warning: Emergency page is undefined!", file=sys.stderr)
            return
        if var is None:
            print("Warning: Emergency variable is undefined!", file=sys.stderr)
            return
        text = self.get_page_text(page)
        if text is None:
            raise EmergencyError('Emergency page ' + page + ' does not exist!')
        text = re.sub('<!--.*?-->', '', text)
        match = re.search(re.escape(var) + '\s*=\s*([0-9]+)', text)
        if match:
            if int(match.group(1)) != 0:
                raise EmergencyError('Emergency halt!')
        else:
            raise EmergencyError('Emergency variable ' + var + ' is not defined in emergency page ' + page + '!')

    ### Initialization ###

    def request_siteinfo(self):
        """Request site information (e.g. main page, namespaces).

        This is used by other methods to do their methody stuff.
        They call this method when required, so there is normally no
        need to call this method explicitly.

        Returns None, but see get_siteinfo().

        """
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
        """Return True if request_siteinfo() has been successfully run."""
        return bool(self._siteinfo)

    def get_siteinfo(self):
        """Return the site information if request_siteinfo() has been
        successfully run, or None otherwise.

        """
        return self._siteinfo

    def request_edittoken(self):
        """Request an edit token (which is used for editing or uploading).

        The edit and upload methods automatically call this method if
        required, so there is normally no need to call this method explicitly.

        Returns None, but see get_edittoken().

        """
        if not self.has_edittoken():
            self.request_siteinfo()
            mainpage = self._siteinfo['general']['mainpage']
            r_edittoken = self._query_api(action='query', prop='info',
                    intoken='edit', titles=mainpage)
            try:
                self._edittoken = unicode(
                        r_edittoken['query']['pages'].values()[0]['edittoken'])
            except(LookupError,TypeError):
                raise WikiError('MediaWiki edit token request failed,' +
                    ' here is the full response: ' +
                    "\n" + pprint.pformat(r_edittoken))

    def has_edittoken(self):
        """Return True if request_edittoken() has been successfully run."""
        return bool(self._edittoken)

    def get_edittoken(self):
        """Return the edit token if request_edittoken() has been
        successfully run, or None otherwise.

        """
        return self._edittoken

    def clear_cached_info(self):
        """Clear the site information and the edit token."""
        self._siteinfo = None
        self._siteinfo_ns = None
        self._siteinfo_ns_normalized = None
        self._edittoken = None

    ### Query methods ###

    def get_page_info(self, title):
        """Return information about a single wiki page.

        title is the requested page name.

        Returns a dict with the following items:
          'categories': list of categories the page belongs to, each
                        represented as a dict with 'ns' and 'title' keys
          'counter':    number of views, unless disabled in server settings
          'lastrevid':  last revision ID
          'length':     page size
          'new':        defined (and empty) iff the page has only one revision
          'ns':         namespace
          'pageid':     page ID
          'redirect':   defined (and empty) iff the page is a redirect
          'revisions':  source code of latest revision (in
                        result['revisions'][0]['*'])
          'title':      title
          'touched':    page_touched property: timestamp that is updated
                        whenever the page must be re-rendered, e.g. due to
                        editing of the page itself or a linked template
          'missing':    Denotes that the page does not exist (or has been
                        deleted). Most other fields are missing if this one is
                        present, only 'title' and 'ns' are there.

        See http://www.mediawiki.org/wiki/API:Properties for more information.
        This method queries info, revisions and categories.

        """
        api_result = self._query_entries((title,), True, ('info', 'revisions', 'categories'))
        try:
            return api_result['query']['pages'].values()[0]
        except(LookupError):
            return None

    def get_page_info_by_id(self, pageid):
        """Return information about a single wiki page.

        pageid is the page ID of the requested page. See the documentation
        for get_page_info() for a description of the result format.

        """
        api_result = self._query_entries((pageid,), False, ('info', 'revisions', 'categories'))
        try:
            return api_result['query']['pages'].values()[0]
        except(LookupError):
            return None

    def get_page_text(self, title):
        """Return the raw wikitext of a single wiki page.

        title is the requested page name.

        """
        api_result = self._query_entries((title,), True, ('revisions',))
        try:
            return api_result['query']['pages'].values()[0]['revisions'][0]['*']
        except(LookupError):
            return None

    def get_page_text_by_id(self, pageid):
        """Return the raw wikitext of a single wiki page.

        pageid is the page ID of the requested page.

        """
        api_result = self._query_entries((pageid,), False, ('revisions',))
        try:
            return api_result['query']['pages'].values()[0]['revisions'][0]['*']
        except(LookupError):
            return None

    def get_multi_page_info(self, titles, redirects=None):
        """Same as get_page_info(), but supports multiple titles.

        titles is the list of requested page names.

        redirects may be None, False or True. If redirects is None, the
        query returns both redirects and non-redirects. If redirects is
        False, the query returns only non-redirects. If redirects is True,
        only redirects are returned. The default is None.

        Returns a list of dicts, each of these dicts being in the same
        format as the return value of get_page_info(). The results are
        sorted alphabetically by title.

        """
        api_result = self._query_entries(titles, True, ('info', 'revisions', 'categories'))
        result = api_result['query']['pages'].values()
        if redirects is not None:
            if redirects:
                result = [x for x in result if 'redirects' in x]
            else:
                result = [x for x in result if 'redirects' not in x]
        return self._natsorted_by_title(result)

    def get_multi_page_info_by_id(self, pageids, redirects=None):
        """Same as get_page_info_by_id(), but supports multiple page IDs.

        pageids is the list of requested page IDs.

        redirects may be None, False or True. If redirects is None, the
        query returns both redirects and non-redirects. If redirects is
        False, the query returns only non-redirects. If redirects is True,
        only redirects are returned. The default is None.

        Returns a list of dicts, each of these dicts being in the same
        format as the return value of get_page_info(). The results are
        sorted alphabetically by title.

        """
        api_result = self._query_entries(pageids, False, ('info', 'revisions', 'categories'))
        result = api_result['query']['pages'].values()
        if redirects is not None:
            if redirects:
                result = [x for x in result if 'redirects' in x]
            else:
                result = [x for x in result if 'redirects' not in x]
        return self._natsorted_by_title(result)

    def get_prefix_list(self, prefix, redirects=None, namespace=None):
        """Return a list of titles of pages with a given prefix.

        prefix is the prefix of the page names that are to be searched.
        Depending on how the namespace parameter is set, it includes the
        namespace prefix, or it doesn't (see below).

        redirects may be None, False or True. If redirects is None, the
        query returns both redirects and non-redirects. If redirects is
        False, the query returns only non-redirects. If redirects is True,
        only redirects are returned. The default is None.

        namespace defines which namespace is searched. The default is None,
        which means the namespace is inferred from the prefix parameter.
        Otherwise, the prefix parameter should not include a namespace prefix
        and namespace may a namespace number or a namespace name (custom and
        localized names are allowed, as well as namespace aliases).

        The returned list is sorted alphabetically.

        """
        self.request_siteinfo()
        api_result = self._query_prefix_list(prefix, redirects, namespace)
        result = [page['title'] for page in api_result['query']['allpages']]
        return self._natsorted(result)

    def get_prefix_list_ids(self, prefix, redirects=None, namespace=None):
        """Return a list of page IDs of pages with a given prefix.

        prefix is the prefix of the page names that are to be searched.
        Depending on how the namespace parameter is set, it includes the
        namespace prefix, or it doesn't (see below).

        redirects may be None, False or True. If redirects is None, the
        query returns both redirects and non-redirects. If redirects is
        False, the query returns only non-redirects. If redirects is True,
        only redirects are returned. The default is None.

        namespace defines which namespace is searched. The default is None,
        which means the namespace is inferred from the prefix parameter.
        Otherwise, the prefix parameter should not include a namespace prefix
        and namespace may a namespace number or a namespace name (custom and
        localized names are allowed, as well as namespace aliases).

        The returned list is sorted numerically.

        """
        self.request_siteinfo()
        api_result = self._query_prefix_list(prefix, redirects, namespace)
        return sorted(int(page['pageid']) for page in api_result['query']['allpages'])

    def get_category_members(self, category, namespace=None):
        """Return a list of titles of pages in the given category.

        category is the name of the category, with or without the
        'Category:' namespace prefix.

        namespace defines which namespaces are searched. The default is None,
        which means that the results are not limited by namespace. Otherwise,
        namespace may a namespace number or a namespace name (custom and
        localized names are allowed, as well as namespace aliases), and
        specifies which namespace the results should be limited to.

        The returned list is sorted alphabetically.

        """
        self.request_siteinfo()
        api_result = self._query_category_members(category, namespace)
        result = [page['title'] for page in api_result['query']['categorymembers']]
        return self._natsorted(result)

    def get_category_members_ids(self, category, namespace=None):
        """Return a list of page IDs of pages in the given category.

        category is the name of the category, with or without the
        'Category:' namespace prefix.

        namespace defines which namespaces are searched. The default is None,
        which means that the results are not limited by namespace. Otherwise,
        namespace may a namespace number or a namespace name (custom and
        localized names are allowed, as well as namespace aliases), and
        specifies which namespace the results should be limited to.

        The returned list is sorted numerically.

        """
        self.request_siteinfo()
        api_result = self._query_category_members(category, namespace)
        return sorted(int(page['pageid']) for page in api_result['query']['categorymembers'])

    def get_all_categories(self, prefix=None):
        """Return a list of all categories.

        To be precise, this actually returns all categories that are
        non-empty or have been at least once in the past. Therefore, an
        empty category whose description page exists is not guaranteed to
        be listed. On the other hand, a "wanted" category, that is, a
        non-empty category with a missing description page will be listed.

        Optionally, prefix limits the search to only the specified prefix.
        The given prefix may, but does not have to include the 'Category:'
        namespace prefix. If prefix is None (the default), category
        names are not limited.

        The returned list is a list of strings (without the 'Category:'
        namespace prefix), sorted alphabetically.

        """
        self.request_siteinfo()
        api_result = self._query_all_categories(prefix)
        result = [page['*'] for page in api_result['query']['allcategories']]
        return self._natsorted(result)

    def get_all_categories_info(self, prefix=None):
        """Return a list of all categories, with additional info.

        Like get_all_categories(), this returns all categories that are
        non-empty or have been at least once in the past. (See there
        for a few notes.)  However, using the additional info given by
        this method, you can for instance filter out categories that are
        currently empty.

        The prefix parameter works identical to the prefix parameter
        in get_all_categories().

        Returns a list of dicts (sorted by title),
        each consisting of the following fields:
          'categoryinfo': a dict with the following fields:
                          'size':    sum of pages, files and subcats
                          'pages':   number of pages in this category
                          'files':   number of files in this category
                          'subcats': number of subcategories in this category
          'ns':           number of the category namespace
          'pageid':       page ID of the description page
          'title':        title of the category, including namespace prefix
          'missing':      Denotes that the description page does not exist (or
                          has been deleted). The 'pageid' field is missing if
                          this one is present.

        """
        self.request_siteinfo()
        api_result = self._query_all_categories_info(prefix)
        result = api_result['query']['pages'].values()
        return self._natsorted_by_title(result)

    ### Parsing wikitext ###

    def expandtemplates(self, text, title=None):
        """Preprocesses wikitext. Expands templates, strips comments, etc.

        text is the wikitext to preprocess.

        title is the title of the page the text is on. This is used when the
        page links to itself, or when links to subpages are present.
        If set to None, defaults to 'API'.

        See http://www.mediawiki.org/wiki/API:Parsing_wikitext.
        """
        return self._query_expandtemplates(text=text, title=title)

    def expandtemplates_page(self, page):
        """Preprocesses wikitext. Expands templates, strips comments, etc.

        page is the title of the page to preprocess.

        See http://www.mediawiki.org/wiki/API:Parsing_wikitext.
        """
        return self._query_expandtemplates(page=page)

    def parse(self, text, title=None, prop=None):
        """Parses wikitext.

        text is the wikitext to parse.

        title is the title of the page the text is on. This is used when the
        page links to itself, or when links to subpages are present.
        If set to None, defaults to 'API'.

        prop is the list of properties to get. If set to None, equivalent
        to ('text', 'langlinks', 'categories', 'links', 'templates',
        'images', 'externallinks', 'sections', 'revid').

        See http://www.mediawiki.org/wiki/API:Parsing_wikitext.
        """
        if prop is not None:
            prop = '|'.join(prop)
        return self._query_parse(text=text, title=title, prop=prop)

    def parse_page(self, page, prop=None):
        """Parses wikitext.

        page is the title of the page to parse.

        prop is the list of properties to get. If set to None, equivalent
        to ('text', 'langlinks', 'categories', 'links', 'templates',
        'images', 'externallinks', 'sections', 'revid').

        See http://www.mediawiki.org/wiki/API:Parsing_wikitext.
        """
        if prop is not None:
            prop = '|'.join(prop)
        return self._query_parse(page=page, prop=prop)

    ### Purging wiki pages ###

    def purge(self, title):
        """Requests that a page is deleted from the server-side article cache
        and rebuilt."""
        r_purge = self._query_api(action='purge', titles=title)
        # TODO verify success

    def purge_multi(self, titles):
        """Requests that multiple pages are deleted from the server-side
        article cache and rebuilt."""
        titles_joined = '|'.join(titles)
        r_purge = self._query_api(action='purge', titles=titles_joined)
        # TODO verify success

    ### Editing and uploading ###

    def edit(self, title, text, summary=None, minor=True, bot=True):
        """Edits or creates a wiki page.

        title is the title of the page to be modified.
        text is the new text.
        summary is the edit summary.
        minor sets the minor flag; by default, it is enabled.
        bot sets the bot flag; by default, it is enabled.

        You should always log in (preferably using a bot account) before
        editing wiki pages. Particularly if doing automated edits, state
        the name and purpose of the bot in the edit summary.

        """
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
        """Uploads a media file to the wiki.

        local_filename is the absolute or relative path to the local file.

        remote_filename is the name that should be used after uploading.
        If it is none, the basename of local_filename is used. The file
        may already exist, in which case it is replaced by the new upload.

        text is the text that should appear on the file page on the wiki.
        License information should appear here, if applicable.

        summary is the upload summary.

        You may have to log in before uploading files. Remember that the
        list of acceptable file types is limited and depends on the wiki
        configuration. Particularly if doing automated upload, state
        the name and purpose of the bot in the upload summary.

        """
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

    ### Name and namespace helper methods ###

    def normalize_name(self, name):
        """Normalize a wiki page name."""
        nsnumber, rest = self.split_name(name)
        return self.combine_name(nsnumber, rest)

    def combine_name(self, ns, rest):
        """Concatenate a namespace name (or number) and rest of page name.

        First this method normalizes the namespace name (using
        normalize_namespace()) and the rest (replacing underscores with
        spaces and converting the first letter to uppercase).
        Then both parts are joined with a colon as a separator.
        The article namespace (ns=0) is properly supported.

        """
        # TODO: normalize special page names?
        nsname = self.normalize_namespace(ns)
        rest = rest.replace('_', ' ')
        rest = rest[0:1].upper() + rest[1:]  # capitalize only first
        if nsname:
            return nsname + ':' + rest
        else:
            return rest

    def split_name(self, name):
        """Split a page name into namespace and rest of page name.

        Returns a 2-tuple. The first element is the namespace number.
        The second element is the rest of the page name (unmodified).

        If the passed name contains no colon or the part before the
        colon is not a known namespace name, the namespace is assumed
        to be 0, aka the main namespace.

        """
        parts = name.split(':', 1)
        assert len(parts) >= 1
        assert len(parts) <= 2
        if len(parts) == 2:
            nsnumber = self.namespace_to_number(parts[0], False)
            if nsnumber is not None:
                return (nsnumber, parts[1])
        return (0, name)  # article namespace

    def normalize_namespace(self, ns):
        """Normalize the namespace name or number ns.

        Converts ns to a namespace number, then returns the localized
        canonical name for the namespace.

        """
        self.request_siteinfo()
        nsnumber = self.namespace_to_number(ns)
        try:
            return self._siteinfo_ns_normalized[nsnumber]
        except(LookupError):
            raise WikiError('No such namespace: ' + unicode(ns))

    def namespace_to_number(self, ns, raise_on_error=True):
        """Convert the namespace name or number ns to a namespace number.

        ns may be a canonical (English), localized, generic or alias name.
        It may also be a namespace number (of type int, *not* in
        string form), in which case this method checks if the given
        namespace number exists.

        If the namespace exists, returns the namespace number.
        Otherwise, if raise_on_error is True, raises a WikiError.
        Otherwise, returns None.

        """
        self.request_siteinfo()
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

    def get_article_path(self, title):
        """Returns the path to the given article page (URL without
        protocol scheme, server and port)."""
        self.request_siteinfo()
        title = self.normalize_name(title)
        return self._siteinfo['general']['articlepath'].replace('$1', title)

    def get_article_url(self, title):
        """Returns the URL to the given article page."""
        self.request_siteinfo()
        return self._siteinfo['general']['server'] + self.get_article_path(title)

    ### Internal methods (low-level query methods) ###

    def _query_prefix_list(self, prefix, redirects=None, namespace=None):
        """Query a list of pages with a given prefix.

        prefix is the prefix of the page names that are to be searched.
        Depending on how the namespace parameter is set, it includes the
        namespace prefix, or it doesn't (see below).

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

        """
        if namespace is None:
            nsnumber, prefix = self.split_name(prefix)
        else:
            nsnumber = self.namespace_to_number(namespace)
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
        nsnumber, rest = self.split_name(category)
        if nsnumber == self.namespace_to_number(''):
            # namespace prefix was omitted, prepend Category:
            nsnumber = self.namespace_to_number('Category')
        category = self.combine_name(nsnumber, rest)
        kw = {'action':'query', 'list':'categorymembers',
                'cmlimit':'max', 'cmtitle':category, 'cmprop':'ids|title'}
        if namespace is not None:
            kw['cmnamespace'] = self.namespace_to_number(namespace)
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

    def _query_all_categories(self, prefix=None):
        """Query all categories.

        prefix is an optional title prefix, with or without the
        'Category:' namespace prefix.

        The exact criteria for a category to be included in the result
        are documented at get_all_categories().

        Returns the API result. This method automatically resumes the query
        if the result limit is exceeded. This method performs a list
        query (as opposed to a generator query).

        Precondition: request_siteinfo() must have been called before.

        """
        kw = {'action':'query', 'list':'allcategories', 'aclimit':'max'}
        if prefix:
            nsnumber, rest = self.split_name(prefix)
            if nsnumber != self.namespace_to_number('') and nsnumber != self.namespace_to_number('Category'):
                raise WikiError('AllCategories prefix is in incorrect namespace')
            kw['acprefix'] = rest
        r_query = self._query_api(**kw)
        try:
            while 'query-continue' in r_query:
                kw['acfrom'] = r_query['query-continue']['allcategories']['acfrom']
                r_query2 = self._query_api(**kw)
                r_query = self._merge_recursive(r_query, r_query2)
            if r_query['query']['allcategories'] is None:
                raise LookupError()
            return r_query
        except(LookupError,TypeError):
            raise WikiError('MediaWiki allcategories query failed,' +
                ' here is the full response: ' +
                "\n" + pprint.pformat(r_query))

    def _query_all_categories_info(self, prefix=None):
        """Query all categories with info.

        prefix is an optional title prefix, with or without the
        'Category:' namespace prefix.

        The exact criteria for a category to be included in the result
        are documented at get_all_categories().

        Returns the API result. This method automatically resumes the query
        if the result limit is exceeded. This method performs a generator
        query (as opposed to a list query).

        Precondition: request_siteinfo() must have been called before.

        """
        kw = {'action':'query', 'generator':'allcategories',
                'gaclimit':'max', 'prop':'categoryinfo'}
        if prefix:
            nsnumber, rest = self.split_name(prefix)
            if nsnumber != self.namespace_to_number('') and nsnumber != self.namespace_to_number('Category'):
                raise WikiError('AllCategories prefix is in incorrect namespace')
            kw['gacprefix'] = rest
        r_query = self._query_api(**kw)
        try:
            while 'query-continue' in r_query:
                kw['gacfrom'] = r_query['query-continue']['allcategories']['gacfrom']
                r_query2 = self._query_api(**kw)
                r_query = self._merge_recursive(r_query, r_query2)
            if r_query['query']['pages'] is None:  # FIXME is this an error?
                raise LookupError()
            return r_query
        except(LookupError,TypeError):
            raise WikiError('MediaWiki allcategories query failed,' +
                ' here is the full response: ' +
                "\n" + pprint.pformat(r_query))

    def _query_entries(self, ids_or_titles, using_titles, prop):
        """Retrieve page data given a list of page IDs or page titles.

        ids_or_titles is a sequence of integers or strings, depending on
        the value of using_titles.

        If using_titles is True, ids_or_titles must be a sequence of strings
        that are interpreted as page titles. If using_titles is False,
        ids_or_titles must be a sequence of integers that are interpreted
        as page IDs.

        prop is the list of properties to get (as a python list).
        The only property for which automatic continuation of the query
        is supported is "categories". If prop includes 'revisions',
        rvprop=content is automatically set.

        Returns the API result.

        """
        chunk_size = 50
        r_total = {}
        for chunk_pos in range(0, len(ids_or_titles), chunk_size):
            chunk = ids_or_titles[chunk_pos : chunk_pos + chunk_size]
            chunk_piped = '|'.join(unicode(x) for x in chunk)
            kw = {'action':'query', 'prop':('|'.join(prop))}
            if 'revisions' in prop:
                kw['rvprop'] = 'content'
            if 'categories' in prop:
                kw['cllimit'] = 'max'
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
                    if 'missing' not in page:
                        page['revisions'] = page['revisions'][0:1]
                # Combine all query results into a total result.
                r_total = self._merge_recursive(r_total, r_query)
            except(LookupError,TypeError):
                raise WikiError('MediaWiki pages query failed,' +
                    ' here is the full response: ' +
                    "\n" + pprint.pformat(r_query))
        return r_total

    def _query_expandtemplates(self, **kw):
        kw['action'] = 'expandtemplates'
        if 'page' in kw and kw['page'] is not None:
            # the 'page' parameter is not supported by action=expandtemplates;
            # fake it
            api_result = self._query_entries((kw['page'],), True, ('revisions',))
            try:
                kw['text'] = api_result['query']['pages'].values()[0]['revisions'][0]['*']
                kw['title'] = kw['page']
                del kw['page']
            except(LookupError):
                raise WikiError('The page you specified does not exist.')
        api_result = self._query_api(**kw)
        try:
            return api_result['expandtemplates']['*']
        except(LookupError):
            raise WikiError('MediaWiki expandtemplates query returned no data.')

    def _query_parse(self, **kw):
        kw['action'] = 'parse'
        api_result = self._query_api(**kw)
        try:
            return api_result['parse']
        except(LookupError):
            raise WikiError('MediaWiki parse query returned no data.')

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
            response_parsed = json.loads(response_uni)
        except(ValueError) as err:
            raise WikiError('Error while accessing ' + self._api + ': ' +
                             unicode(err) + "\n\n" +
                             "Response was:\n" +
                             self._truncate_text(response_uni, 500))
        if __debug__:
            print("Result:")
            pprint.pprint(response_parsed)
            print()
        if 'error' in response_parsed:
            raise WikiError('Error while accessing ' + self._api + ': ' +
                    response_parsed['error']['info'])
        if 'warnings' in response_parsed:
            all_api_warnings = [x['*'] for x in response_parsed['warnings'].values()]
            raise WikiError('Error while accessing ' + self._api + ': ' +
                    "\n".join(all_api_warnings))
        return response_parsed

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

    # The following two methods are snipped from the eighth comment in
    #   http://code.activestate.com/recipes/285264-natural-string-sorting/
    # By Seo Sanghyeon.  Some changes by Connelly Barnes & Spondon Saha

    def _try_int(self, s):
        """Convert to integer if possible."""
        try:
            return int(s)
        except:
            return s

    def _natsort_key(self, s):
        """Computes a key for natural string sorting."""
        return map(self._try_int, re.findall(r'(\d+|\D+)', s))

    def _natsorted(self, l):
        return sorted(l, key=self._natsort_key)

    def _natsorted_by_title(self, l):
        return sorted(l, key=lambda x: self._natsort_key(x['title']))
