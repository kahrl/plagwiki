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


config = Config(os.path.dirname(os.path.abspath(__file__)) + '/../config')

try:
    with config.create_wiki_client('VroniPlag') as client:
        client.check_emergency()

        summary = 'PlagWiki-Bot - test von action=edit'
        for page in ('Benutzer:Kahrlbot/Test', 'Benutzer:Kahrlbot/Test2'):
            oldtext = client.get_page_text(page)
            if oldtext is None:
                print('Page does not exist: ' + page)
                oldtext = ''
            newtext = oldtext + "\nDieser Text stammt von Kahrlbot"
            print('Editing page: ' + page)
            client.check_emergency()
            client.edit(page, newtext, summary)

except(EmergencyError) as err:
    print(err)
except(KeyboardInterrupt) as err:
    print()
    print("Interrupted.")
except(EOFError) as err:
    print()
    print('Quitting.')
