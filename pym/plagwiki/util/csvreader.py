#!/usr/bin/env python
# -*- coding: utf-8 -*-

# ease eventual Python 3 transition
from __future__ import division, print_function, unicode_literals

import re
from plagwiki.util.plagerror import PlagError


def csv_to_list(text, separators = ",;"):
    assert ' ' not in separators   # broken by ws_pattern
    assert "\t" not in separators  # same
    assert "\n" not in separators  # same
    ws_pattern = re.compile(r'\s*', re.UNICODE | re.DOTALL)
    lex_pattern = re.compile(r'[- \w]+|"([^"\\]|\\.)*"', re.UNICODE | re.DOTALL)
    unescape_pattern = re.compile(r'\\(\\|")', re.UNICODE | re.DOTALL)
    lines = []
    last_line = []
    was_separator = False
    pos = 0
    while pos < len(text):
        ws_match = ws_pattern.match(text, pos)
        assert ws_match is not None
        ws_end = ws_match.end()
        if text.find("\n", pos, ws_end) != -1:
            if not was_separator and last_line:
                lines.append(last_line)
                last_line = []
        if ws_end == len(text):
            break
        if text[ws_end] in separators:
            if was_separator:
                last_line.append('')
            else:
                was_separator = True
            pos = ws_end + 1
        else:
            if last_line and not was_separator:
                raise PlagError("Syntax error in CSV data, separator expected near: " + text[ws_end:ws_end+10].lstrip())
            lex_match = lex_pattern.match(text, ws_end)
            if lex_match is None:
                raise PlagError("Syntax error in CSV data near: " + text[ws_end:ws_end+10].lstrip())
            lex_start = lex_match.start()
            lex_end = lex_match.end()
            if text[lex_start] == '"' and text[lex_end-1] == '"' and lex_end >= lex_start + 2:
                last_line.append(unescape_pattern.sub(r'\1', text[lex_start+1:lex_end-1]))
            else:
                last_line.append(text[lex_start:lex_end])
            pos = lex_end
            was_separator = False
    if was_separator:
        raise PlagError("Syntax error in CSV data: last row ended with separator")
    if last_line:
        lines.append(last_line)
        last_line = []
    return lines
