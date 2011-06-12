#!/usr/bin/env python
# -*- coding: utf-8 -*-

# ease eventual Python 3 transition
from __future__ import division, print_function, unicode_literals

class PlagError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return unicode(self.value).encode('utf-8')
