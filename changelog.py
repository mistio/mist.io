#!/usr/bin/env python


import os
import re
import sys
import json
import argparse
import datetime
import tempfile
import subprocess
import dateutil.parser

import requests


MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
          'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')


class InputError(Exception):
    pass


def prompt_string(msg, default=None, match='', required=True,
                  retry=True, confirm=False):
    """Display a CLI prompt so that the user can provide a value

    Params:
    msg         Prompt message to display, colon and space are automatically
                added.
    default     Default value to display.
    match       If provided, user input must match this regex string.
    required    If True, user input must not be empty.
    retry       If True and invalid value, prompt again.
    confirm     If True, user is asked to confirm input value.
    """

    if default is not None and (default or not required):
        prompt = "%s (default is '%s'): " % (msg, default)
    else:
        prompt = "%s: " % msg
    while True:
        value = raw_input(prompt).strip() or default or ''
        try:
            if required and not value:
                raise InputError("Required value can't be empty.")
            if match and not re.match(match, value):
                raise InputError("Input value must match '%s'." % match)
        except InputError as exc:
            if retry:
                print >> sys.stderr, "WARNING: %s" % exc
                continue
            raise
        if confirm:
            if not prompt_boolean(
                "Input value is '%s'. Please confirm." % value,
                default=True, retry=True
            ):
                continue
        break
    return value


def prompt_boolean(msg, default=None, retry=True):
    """Display a CLI prompt so that the user can provide a yes/no value

    Params:
    msg         Prompt message to display, colon, space and [y/n] are
                automatically added.
    default     Default value to display.
    retry       If True and invalid value, prompt again.
    """
    assert default in (True, False, None)
    if default is True:
        opts = '[Y/n]'
    elif default is False:
        opts = '[y/N]'
    else:
        opts = '[y/n]'
    prompt = '%s %s' % (msg, opts)
    value = prompt_string(prompt, match=r'^[yYnN]?$',
                          required=default is None, retry=retry).lower()
    if value == 'y':
        return True
    elif value == 'n':
        return False
    else:
        assert not value, value
        assert default is not None
        return default


def editor(text, tmp_suffix='.tmp'):
    """Spawn $EDITOR (defaults to vim) for user to edit given text"""
    if isinstance(text, unicode):
        text = text.encode('utf8')
    with tempfile.NamedTemporaryFile(suffix=tmp_suffix) as tf:
        tf.write(text)
        tf.flush()
        subprocess.call([os.getenv('EDITOR', 'vim'), tf.name])
        tf.seek(0)
        return tf.read()


def crop_line_padding(lines):
    """Removes padding white space from lines list.

    1. Remove all trailing whitespace from start and end of all lines.
    2. Remove empty lines in start and end of list
    """
    if isinstance(lines, basestring):
        lines = lines.splitlines()
    lines = [line.strip() for line in lines]
    for i, line in enumerate(lines):
        if line:
            lines = lines[i:]
            break
    for i, line in enumerate(reversed(lines)):
        if line:
            lines = lines[:-i or len(lines)]
            break
    return lines


class Changelog(object):
    """Holds state of entire changelog"""

    def __init__(self):
        self.versions = []

    @classmethod
    def from_string(cls, string):
        lines = crop_line_padding(string)
        changelog = cls()
        if not lines:
            print >> sys.stderr, "WARNING: Changelog is emtpy"
            return changelog
        assert re.match('^#\s*changelog\s*$',
                        lines[0].lower()), "Changelog missing top header."
        lines = crop_line_padding(lines[1:])
        sections = []
        for line in lines:
            if re.match('^##[^#]', line):
                sections.append([])
            else:
                assert sections, ("Changelog body doesn't start "
                                  "with level two header.")
            sections[-1].append(line)
        for section in sections:
            changelog.versions.append(
                Version.from_string('\n'.join(section))
            )
        return changelog

    @classmethod
    def from_file(cls, path):
        try:
            with open(path, 'r') as fobj:
                return cls.from_string(fobj.read())
        except IOError as exc:
            print >> sys.stderr, "WARNING: %r" % exc
            return cls()

    def to_string(self):
        return '# Changelog\n\n\n' + '\n\n'.join(map(Version.to_string,
                                                     reversed(self.versions)))

    def __str__(self):
        return self.to_string()

    def to_file(self, path):
        print >> sys.stderr, "INFO: Writing changelog to '%s'." % path
        with open(path, 'w') as fobj:
            fobj.write(self.to_string())

    def to_dict(self):
        return {
            'versions': [version.to_dict() for version in self.versions],
        }

    def show(self, as_json=False):
        print '----CHANGELOG-START----'
        if as_json:
            print json.dumps(self.to_dict())
        else:
            print self.to_string()
        print '----CHANGELOG-END----'


class Version(object):
    """Holds changelog information for a particular version"""

    def __init__(self, name, day, month, year, notes=''):

        match = re.match(r'^v\d+\.\d+\.\d+(-.+)?$', name)
        assert match, "Invalid version name '%s'" % name
        self.name = name
        self.prerelease = bool(match.groups()[0])

        assert isinstance(day, int) and 0 < day < 32, "Invalid day '%s'" % day
        self.day = day
        month = month.capitalize()
        assert month in MONTHS, month
        self.month = month
        assert isinstance(year, int) and 2017 <= year < 2030, year
        self.year = year

        self.notes = notes

        self.changes = []

    @classmethod
    def from_string(cls, string):
        lines = crop_line_padding(string)

        months = '|'.join(MONTHS)
        match = re.match(
            r'^##\s*(v\d+\.\d+\.\d+(?:-.+)?)\s*'
            r'\(\s*(\d+)\s*(%s)\s*(\d+)\s*\)\s*$' % months,
            lines[0], re.IGNORECASE
        )
        assert match, "Invalid version header '%s'" % lines[0]
        name, day, month, year = match.groups()

        lines = crop_line_padding(lines[1:])
        notes = []
        for i, line in enumerate(lines):
            if not re.match(r'^###\s*changes\s*$', line, re.IGNORECASE):
                notes.append(line)
            else:
                break
        notes = '\n'.join(notes)
        lines = filter(None, crop_line_padding(lines[i+1:]))

        version = cls(name, int(day), month, int(year), notes)
        for line in lines:
            version.changes.append(Change.from_string(line))
        return version

    def to_string(self):
        msg = '## %s (%s %s %s)\n\n' % (self.name, self.day, self.month,
                                        self.year)
        if self.notes:
            msg += '%s\n\n' % self.notes
        msg += '### Changes\n\n'
        for change in self.changes:
            msg += '%s\n' % change.to_string()
        return msg

    def __str__(self):
        return self.to_string()

    def to_dict(self):
        return {
            'name': self.name,
            'prerelease': self.prerelease,
            'date': {
                'day': self.day,
                'month': self.month,
                'year': self.year,
            },
            'notes': self.notes,
            'changes': [change.to_dict() for change in self.changes],
        }


class Change(object):
    """Holds information about a particular change"""

    KINDS = ('Changes', 'Bugfix', 'Feature', 'Optimization')

    def __init__(self, title, kind='Changes', mr=0):

        assert title
        self.title = title

        assert kind in self.KINDS, "Invalid change type '%s'" % kind
        self.kind = kind

        assert not mr or isinstance(mr, int), "Invalid MR number '%s'" % mr
        self.mr = mr

    @classmethod
    def from_string(cls, string):
        kinds = '|'.join(cls.KINDS)
        regex = r'^\s*[\*-]?\s*(%s)\s*:\s*(.*?)\s*(?:\(!([0-9]+)\))?\s*$' % (
            kinds)
        match = re.match(regex, string, re.IGNORECASE)
        assert match, "Couldn't parse change information from string '%s'." % (
            string)
        kind, title, mr = match.groups()
        return cls(title, kind.capitalize(), int(mr or 0))

    def to_string(self):
        msg = "* %s: %s" % (self.kind, self.title)
        if self.mr:
            msg = "%s (!%d)" % (msg, self.mr)
        return msg

    def __str__(self):
        return self.to_string()

    def to_dict(self):
        return {
            'title': self.title,
            'kind': self.kind,
            'mr': self.mr or None,
        }


class GitlabRequest(object):
    """Wrapper around `requests` to help querying Gitlab's API"""
    def __init__(self, url='https://gitlab.ops.mist.io', repo='mistio/mist.io',
                 token=''):
        if url.endswith('/'):
            url = url[:-1]
        self.url = url
        self.repo = repo
        self.token = token
        self.repo_id = ''
        print >> sys.stderr, "INFO: Searching for id of project %s" % self.repo
        self.repo_id = str(self.get('')['id'])
        print >> sys.stderr, "INFO: Project id is %s" % self.repo_id

    def get(self, url, params=None, **kwargs):
        if url.startswith('/'):
            url = url[1:]
        quoted_repo = (self.repo_id or self.repo).replace('/', '%2F')
        url = '%s/api/v4/projects/%s/%s' % (self.url, quoted_repo, url)
        if self.token:
            kwargs.setdefault('headers', {})['PRIVATE-TOKEN'] = self.token

        resp = requests.get(url, params=params, **kwargs)

        if not resp.ok:
            print >> sys.stderr, "ERROR: Response failed (%s)" % (
                resp.status_code)
            print >> sys.stderr, resp.text
            raise Exception(resp)
        try:
            return resp.json()
        except Exception:
            print >> sys.stderr, "ERROR: Error decoding json response"
            print >> sys.stderr, resp.text
            raise


def get_mrs(gitlab, branches=('master', 'staging'), since=None):
    """Find MR's from gitlab

    Params:

        gitlab              GitlabRequest instance.
        since               Only return MR's merged since given datetime obj.
        branches            Only return MR's merged to given branches.
    """

    assert since is None or isinstance(since, datetime.datetime)

    # Find all MR's, sorted by updated_at, optionally limit updated_at with
    # since param.
    mrs = []
    per_page = 100
    page = 1
    sys.stderr.write("INFO: Fetching MR's...")
    sys.stderr.flush()
    while True:
        batch = gitlab.get('merge_requests', {'state': 'merged',
                                              'order_by': 'updated_at',
                                              'sort': 'desc',
                                              'per_page': per_page,
                                              'page': page})
        sys.stderr.write(
            "\rINFO: Fetching MR's...  %d" % (len(mrs) + len(batch)))
        sys.stderr.flush()
        break_updated_at = False
        for mr in batch:
            updated_at = dateutil.parser.parse(
                mr['updated_at']
            ).replace(tzinfo=None)
            if since and updated_at < since:
                break_updated_at = True
                break
            if branches and mr['target_branch'] not in branches:
                continue
            mrs.append(mr)
        if break_updated_at:
            break
        if len(batch) < per_page:
            break
        page += 1
    print >> sys.stderr

    if since:
        sys.stderr.write("INFO: Fetching MR merge commits... 0/%d" % len(mrs))
        sys.stderr.flush()
        for i, mr in enumerate(list(mrs)):
            sys.stderr.write(
                "\rINFO: Fetching MR merge commits...  %d/%d" % (i + 1,
                                                                 len(mrs)))
            sys.stderr.flush()
            sha = mr['merge_commit_sha']
            assert sha
            commit = gitlab.get('repository/commits/%s' % sha)
            created_at = dateutil.parser.parse(
                commit['created_at']
            ).replace(tzinfo=None)
            if created_at < since:
                mrs.pop(i)
        print >> sys.stderr

    print >> sys.stderr, "Returning %d mrs" % len(mrs)

    return mrs


def parse_args():
    """Initialize argparse and parse args"""

    argparser = argparse.ArgumentParser(
        description="Add version info to changelog"
    )

    # Create subparsers for different actions.
    subparsers = argparser.add_subparsers(help="Action to perform.",
                                          dest="action")

    show_parser = subparsers.add_parser('show', help="Display changelog.")
    show_parser.add_argument('-j', '--json', action='store_true',
                             help="Display as json dict, not markdown text.")

    add_parser = subparsers.add_parser('add',
                                       help="Add new version to changelog.")
    add_parser.add_argument('-t', '--token',
                            default=os.getenv('GITLAB_TOKEN', ''),
                            help="Token to authenticate to Gitlab's API. "
                                 "Taken by GITLAB_TOKEN env variable by "
                                 "default.")
    add_parser.add_argument('-b', '--branch', dest='branches', action='append',
                            help="Only include MR's merged into this branch. "
                                 "Can be specified multiple times. "
                                 "Default includes MR's to master & staging.")

    # Common args
    for parser in (argparser, show_parser, add_parser, ):
        parser.add_argument('-f', '--file', default='CHANGELOG.md',
                            help="Changelog file to read/write info.")
    for parser in (add_parser, ):
        parser.add_argument('version', help="Target version.")

    args = argparser.parse_args()

    if hasattr(args, 'branches') and not args.branches:
        args.branches = ['master', 'staging']
    return args


def main():
    args = parse_args()

    changelog = Changelog.from_file(args.file)

    if args.action == 'show':
        if args.json:
            print changelog.to_dict()
        else:
            changelog.show()
    elif args.action == 'add':
        gitlab = GitlabRequest(token=args.token)
        now = datetime.datetime.now()
        version = Version(args.version,
                          int(now.day), MONTHS[now.month - 1], int(now.year))
        last_version = None
        since = None
        if changelog.versions:
            last_version = changelog.versions[0]
            print >> sys.stderr, "INFO: Last version is '%s'." % (
                last_version.name)
            try:
                last_tag = gitlab.get(
                    'repository/tags/%s' % last_version.name
                )
            except:
                print >> sys.stderr, ("ERROR: Can't find previous release "
                                      "'%s' on Gitlab." % last_version.name)
                raise
            since = dateutil.parser.parse(
                last_tag['commit']['committed_date']
            ).replace(tzinfo=None)
        mrs = get_mrs(gitlab, branches=args.branches, since=since)
        for mr in mrs:
            version.changes.append(Change(mr['title'], mr=mr['id']))
        text = version.to_string()
        if last_version is not None and last_version.prerelease:
            for change in last_version.changes:
                text += '%s\n' % change.to_string()
            changelog.versions[-1].pop()
        while True:
            text = editor(text, tmp_suffix='.md')
            try:
                version = Version.from_string(text)
            except Exception as exc:
                print >> sys.stderr, "WARNING: Error parsing change: %r" % exc
                if not prompt_boolean("Re-edit changelog", default=True):
                    print >> sys.stderr, "ERROR: Exiting."
                    sys.exit(1)
            else:
                break
        changelog.versions.append(version)
        changelog.show()
        if prompt_boolean("Do you wish to update %s?" % args.file):
            changelog.to_file(args.file)


if __name__ == '__main__':
    main()
