#!/usr/bin/env python
# -*- coding: utf-8 -*-

# This bot finds pages that are not in the barcode.

# ease eventual Python 3 transition
from __future__ import division, print_function, unicode_literals

import os, sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)) + '/../pym')

from plagwiki.config import Config
from plagwiki.loaders.emergencyerror import EmergencyError
import pprint
import re

config = Config(os.path.dirname(os.path.abspath(__file__)) + '/../config')

plagnames = []
for arg in sys.argv[1:]:
    if arg[0:1] == '-':
        print('Unknown option: ' + arg, file=sys.stdout)
        sys.exit(1)
    elif config.has_plag(arg):
        plagnames.append(arg)
    else:
        print('Unknown plag: ' + arg, file=sys.stdout)
        sys.exit(1)

try:
    for plagname in plagnames:
        print(plagname)
        plag = config.get_plag(plagname)
        if not plag.barcode:
            print('Error: ' + plagname + ' has no barcode page')
            continue
        with config.create_plag_client(plagname) as client:
            barcode_text = client.get_page_text(plag.barcode)
            if barcode_text is None:
                print('Error: Unable to load barcode page for ' + plagname, file=sys.stderr)
                continue
            #pprint.pprint(barcode_text)
            # remove HTML comments
            barcode_text = re.sub('<!--.*?-->', '', barcode_text)
            # find correct section in barcode page
            barcode_match = re.search(r'^==\s*Seiten, die aktuell im Barcode sind\s*==$(?:(?!==).)*?(\d(?:\d|,|\n|<br\s*/>|\$)*)', barcode_text, re.MULTILINE | re.UNICODE | re.DOTALL)
            if not barcode_match:
                print('Error: Unable to parse barcode page!')
            barcode_matchtext = re.sub(r'<br\s*/>|\n|\$', '', barcode_match.group(1))
            #pprint.pprint(barcode_matchtext)
            barcode_numbers = [int(x) for x in barcode_matchtext.split(',')
                               if re.match('\d+', x)]
            print(','.join(unicode(x) for x in barcode_numbers))


except(EmergencyError) as err:
    print(err)
except(KeyboardInterrupt) as err:
    print()
    print("Interrupted.")
except(EOFError) as err:
    print()
    print('Quitting.')
