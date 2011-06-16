#!/usr/bin/env python
# -*- coding: utf-8 -*-

# This bot finds all categories in VroniPlag of form <prefix>_<number>
# and removes pages from them

# ease eventual Python 3 transition
from __future__ import division, print_function, unicode_literals

import os, sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/../pym')

from plagwiki.config import Config
from plagwiki.loaders.emergencyerror import EmergencyError
import pprint
import re

def ask_user(prompt, default=None):
    while True:
        inp = raw_input(prompt).strip()
        if inp == '' and default is not None:
            return default
        if inp.lower() == 'y' or inp.lower() == 'yes':
            return True
        if inp.lower() == 'n' or inp.lower() == 'no':
            return False
        print('Sorry, response \'' + inp + '\' not understood.')

def remove_category_plb(oldtext, fulltitle):
    def repl(match):
        if match.group(1) and match.group(2):
            return match.group(2)
        else:
            return ''
    return re.sub('((?:&#13;&#10;)?)\[\[' + fulltitle.replace(' ', '[ _]') + '\]\]((?:&#13;&#10;)?)', repl, oldtext)


config = Config(os.path.dirname(os.path.abspath(__file__)) + '/../config')

try:
    with config.create_wiki_client('VroniPlag') as client:
        client.check_emergency()
        #all_categories_info = client.get_all_categories_info()
        all_categories_info = client.get_all_categories_info('Mm')
        for categoryinfo in all_categories_info:
            client.check_emergency()

            # Check category title
            fulltitle = categoryinfo['title']
            title = client.split_name(categoryinfo['title'])[1]
            if not re.match('^[A-Za-z]{2,3} [0-9]{1,3}$', title):
                continue

            # Check category size
            if categoryinfo['categoryinfo']['size'] == 0:
                if 'missing' not in categoryinfo:
                    print()
                    print('*** Please delete ' + fulltitle + ', it is empty ***')
                continue
            if categoryinfo['categoryinfo']['pages'] == 0:
                print()
                print('*** Category ' + title + ' contains no pages, but is not empty. Please check this. ***')
                continue

            # Ask the user for permission to go ahead
            pages_in_category = client.get_category_members(title)
            print()
            print('*** Found offending category: ' + title + ' ***')
            print('Members of this category:')
            for page in pages_in_category:
                print('  '+page)
            if not ask_user('Do you want to remove these pages from the category? [Y/n] ', True):
                print('Skipping ' + title)
                continue

            # Go do it already
            summary = 'PlagWiki-Bot - entferne überflüssige Plagiatsseitenkategorie (' + title + ')'
            for page in pages_in_category:
                oldtext = client.get_page_text(page)
                if oldtext is None:
                    print('Page does not exist: ' + page)
                    continue
                newtext = remove_category_plb(oldtext, fulltitle)
                if len(newtext) <= len(oldtext) - len(title) - 1:
                    print('Editing page: ' + page)
                    pprint.pprint(oldtext)
                    pprint.pprint(newtext)
                    if ask_user("Really?"):
                        client.check_emergency()
                        client.edit(page, newtext, summary)
                else:
                    print('Page seems unchanged: ' + page)

except(EmergencyError) as err:
    print(err)
except(KeyboardInterrupt) as err:
    print()
    print("Interrupted.")
except(EOFError) as err:
    print()
    print('Quitting.')
