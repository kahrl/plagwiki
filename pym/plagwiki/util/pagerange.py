#!/usr/bin/env python
# -*- coding: utf-8 -*-

# ease eventual Python 3 transition
from __future__ import division, print_function, unicode_literals

import cStringIO
import re
from plagwiki.util.plagerror import PlagError


class PageRange(object):
    def parse(s):
        print("parsing page range: "+s)
        s = unicode(s)
        parts = s.split('-')
        if len(parts) == 1:
            return PageRange(parts[0], parts[0])
        else:
            return PageRange(parts[0], parts[1])
    parse = staticmethod(parse)

    def __init__(self, min_label, max_label):
        if min_label == max_label:
            self.prefix = min_label
            self.infix = None
            self.suffix = ''
            self.first = 0
            self.last = 0
        else:
            # find longest common prefix
            max_prefix = min(len(min_label), len(max_label)) - 1
            prefix_len = 0
            while prefix_len < max_prefix and min_label[prefix_len] == max_label[prefix_len]:
                prefix_len += 1
            # find longest common suffix
            max_suffix = min(len(min_label), len(max_label)) - prefix_len - 1
            suffix_len = 0
            while suffix_len < max_suffix and min_label[-1-suffix_len] == max_label[-1-suffix_len]:
                suffix_len += 1
            # initialize object
            self.prefix = min_label[:prefix_len]
            self.infix = None
            self.suffix = min_label[len(min_label)-suffix_len:]
            self.first = 0
            self.last = 0
            # run a heuristic to find out the page number format
            min_infix = min_label[prefix_len:len(min_label)-suffix_len]
            max_infix = max_label[prefix_len:len(max_label)-suffix_len]
            if re.match('^\d+$', min_infix) and re.match('^\d+$', max_infix):
                self.infix = 'arabic'
                valid_characters = PageRange._char_range('0', '9')
            elif re.match('^[ivxlcdm]+$', min_infix) and re.match('^[ivxlcdm]+$', max_infix):
                self.infix = 'roman'
                valid_characters = 'ivxlcdm'
            elif re.match('^[IVXLCDM]+$', min_infix) and re.match('^[IVXLCDM]+$', max_infix):
                self.infix = 'Roman'
                valid_characters = 'IVXLCDM'
            elif re.match('^[a-z]+$', min_infix) and re.match('^[a-z]+$', max_infix):
                self.infix = 'alph'
                valid_characters = PageRange._char_range('a', 'z')
            elif re.match('^[A-Z]+$', min_infix) and re.match('^[A-Z]+$', max_infix):
                self.infix = 'Alph'
                valid_characters = PageRange._char_range('A', 'Z')
            else:
                raise PlagError('Page range: Unable to derive page number format: ' + min_label + ', ' + max_label)
            # make the infix as long as possible
            while self.prefix and self.prefix[-1] in valid_characters:
                min_infix = self.prefix[-1] + min_infix
                max_infix = self.prefix[-1] + max_infix
                self.prefix = self.prefix[:-1]
            while self.suffix and self.suffix[0] in valid_characters:
                min_infix += self.suffix[0]
                max_infix += self.suffix[0]
                self.suffix = self.suffix[1:]
            # parse min and max page number
            self.first = PageRange.parse_number(min_infix, self.infix)
            self.last = PageRange.parse_number(max_infix, self.infix)
            if self.first >= self.last:
                raise PlagError('Page range: Page numbers are not increasing: ' + min_label + ', ' + max_label)
            if min_infix != PageRange.format_number(self.first, self.infix):
                raise PlagError('Page range: Page number ' + min_label + ' is not canonical, expected ' + self.prefix + PageRange.format_number(self.first, self.infix) + self.suffix)
            if max_infix != PageRange.format_number(self.last, self.infix):
                raise PlagError('Page range: Page number ' + max_label + ' is not canonical, expected ' + self.prefix + PageRange.format_number(self.last, self.infix) + self.suffix)


    def count(self):
        return self.last - self.first + 1

    def __getitem__(self, index):
        if index < 0 or index >= self.count():
            raise IndexError('Index into PageRange is out of bounds')
        if self.infix is None:
            return self.prefix + self.suffix
        else:
            return self.prefix + PageRange.format_number(self.first+index, self.infix) + self.suffix

    def __repr__(self):
        c = self.count()
        if c <= 1:
            return '<PageRange ' + repr(self[0]) + '>'
        elif c == 2:
            return '<PageRange ' + repr(self[0]) + ', ' + repr(self[1]) + '>'
        elif c == 3:
            return '<PageRange ' + repr(self[0]) + ', ' + repr(self[1]) + ', ' + repr(self[2]) + '>'
        else:
            # We return the second element too so that during debugging
            # it is easy to see if PageRange's heuristics chose the
            # wrong number format (e.g. roman where alph was intended).
            return '<PageRange ' + repr(self[0]) + ', ' + repr(self[1]) + ', ... ' + repr(self[c-1]) + '>'

    def format_number(n, how):
        if how == 'arabic':
            return PageRange.format_arabic(n)
        elif how == 'roman':
            return PageRange.format_roman(n)
        elif how == 'Roman':
            return PageRange.format_roman(n).upper()
        elif how == 'alph':
            return PageRange.format_alph(n)
        elif how == 'Alph':
            return PageRange.format_alph(n).upper()
        else:
            raise PlagError('unknown number format: ' + how)
    format_number = staticmethod(format_number)

    def parse_number(s, how):
        how = how.lower()
        if how == 'arabic':
            return PageRange.parse_arabic(s)
        elif how == 'roman' or how == 'Roman':
            return PageRange.parse_roman(s)
        elif how == 'alph' or how == 'Alph':
            return PageRange.parse_alph(s)
        else:
            raise PlagError('unknown number format: ' + how)
    parse_number = staticmethod(parse_number)

    def format_arabic(n):
        if n < 0:
            raise PlagError('arabic representation undefined for number ' + unicode(n))
        return unicode(n)
    format_arabic = staticmethod(format_arabic)

    def parse_arabic(s):
        s = unicode(s)
        if re.match('\d+', s):
            return int(s)
        else:
            raise PlagError('invalid arabic number: ' + s)
    parse_arabic = staticmethod(parse_arabic)

    def format_roman(n):
        if n <= 0:
            raise PlagError('roman representation undefined for number ' + unicode(n))
        rom = cStringIO.StringIO()
        while n >= 1000:
            rom.write('m')
            n -= 1000
        if n >= 900:
            rom.write('cm')
            n -= 900
        if n >= 500:
            rom.write('d')
            n -= 500
        if n >= 400:
            rom.write('cd')
            n -= 400
        while n >= 100:
            rom.write('c')
            n -= 100
        if n >= 90:
            rom.write('xc')
            n -= 90
        if n >= 50:
            rom.write('l')
            n -= 50
        if n >= 40:
            rom.write('xl')
            n -= 40
        while n >= 10:
            rom.write('x')
            n -= 10
        if n >= 9:
            rom.write('ix')
            n -= 9
        if n >= 5:
            rom.write('v')
            n -= 5
        if n >= 4:
            rom.write('iv')
            n -= 4
        while n >= 1:
            rom.write('i')
            n -= 1
        return unicode(rom.getvalue())
    format_roman = staticmethod(format_roman)

    def parse_roman(s):
        s = unicode(s)
        if re.match('[ivxlcdm]+', s, re.IGNORECASE):
            digits = [PageRange.parse_roman_digit(x) for x in s]
            n = 0
            pos = 0
            while pos < len(digits):
                if pos < len(digits) - 1 and digits[pos] < digits[pos+1]:
                    n += digits[pos+1] - digits[pos]
                    pos += 2
                else:
                    n += digits[pos]
                    pos += 1
            return n
        else:
            raise PlagError('invalid roman number: ' + s)
    parse_roman = staticmethod(parse_roman)

    def parse_roman_digit(s):
        s = unicode(s).lower()
        if s == 'i':
            return 1
        elif s == 'v':
            return 5
        elif s == 'x':
            return 10
        elif s == 'l':
            return 50
        elif s == 'c':
            return 100
        elif s == 'd':
            return 500
        elif s == 'm':
            return 1000
        else:
            raise PlagError('invalid roman digit: ' + s)
    parse_roman_digit = staticmethod(parse_roman_digit)

    def format_alph(n):
        if n <= 0:
            raise PlagError('alph representation undefined for number ' + unicode(n))
        digits = 1
        n -= 1
        while n >= 26**digits:
            n -= 26**digits
            digits += 1
        alph = cStringIO.StringIO()
        for i in reversed(range(digits)):
            alph.write(chr(ord('a') + (n//26**i) % 26))
        return unicode(alph.getvalue())
    format_alph = staticmethod(format_alph)

    def parse_alph(s):
        s = unicode(s)
        if re.match('[a-z]+', s, re.IGNORECASE):
            n = 0
            for letter in s:
                n = (n * 26) + ord(letter.lower()) - ord('a')
            for i in range(len(s)):
                n += 26**i
            return n
        else:
            raise PlagError('invalid alph number: ' + s)
    parse_alph = staticmethod(parse_alph)

    def _char_range(min_char, max_char):
        return ''.join([chr(x) for x in range(ord(min_char), ord(max_char)+1)])
    _char_range = staticmethod(_char_range)
