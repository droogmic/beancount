"""
Example interactive extractor
"""
__copyright__ = "Copyright (C) 2018  Michael Droogleever"
__license__ = "MIT"

import sys
from os import path
import io
import argparse
import itertools
import logging
import traceback
import textwrap
import curses
import runpy

from beancount import loader
from beancount.core import data
from beancount.core import getters
from beancount.core import flags
from beancount.parser import printer
from beancount.ingest import similar
from beancount.ingest import cache
from beancount.ingest.interactive.interactive import select_account
from beancount.ingest.interactive import guesser

# The format for the header in the extracted output.
# Override the header on extracted text (if desired).
HEADER = ';; -*- mode: beancount -*-\n'

# The format for the section titles in the extracted output.
# You may override this value from your .import script.
SECTION = '**** {}'

# Name of metadata field to be set to indicate that the entry is a likely duplicate.
DUPLICATE_META = '__duplicate__'


def extract_from_file(filename, importer,
                      existing_entries=None,
                      min_date=None,
                      allow_none_for_tags_and_links=False):
    """Import entries from file 'filename' with the given matches,

    Also cross-check against a list of provided 'existing_entries' entries,
    de-duplicating and possibly auto-categorizing.

    Args:
      filename: The name of the file to import.
      importer: An importer object that matched the file.
      existing_entries: A list of existing entries parsed from a ledger, used to
        detect duplicates and automatically complete or categorize transactions.
      min_date: A date before which entries should be ignored. This is useful
        when an account has a valid check/assert; we could just ignore whatever
        comes before, if desired.
      allow_none_for_tags_and_links: A boolean, whether to allow plugins to
        generate Transaction objects with None as value for the 'tags' or 'links'
        attributes.
    Returns:
      A list of new imported entries and a subset of these which have been
      identified as possible duplicates.
    Raises:
      Exception: If there is an error in the importer's extract() method.
    """
    # Extract the entries.
    file = cache.get_file(filename)

    # Note: Let the exception through on purpose. This makes developing
    # importers much easier by rendering the details of the exceptions.
    new_entries = importer.extract(file)
    if not new_entries:
        return [], []

    # Ensure that the entries are typed correctly.
    for entry in new_entries:
        data.sanity_check_types(entry, allow_none_for_tags_and_links)

    # Filter out entries with dates before 'min_date'.
    if min_date:
        new_entries = list(itertools.dropwhile(lambda x: x.date < min_date,
                                               new_entries))

    # Find potential matching entries.
    duplicate_entries = []
    if existing_entries is not None:
        duplicate_pairs = similar.find_similar_entries(new_entries, existing_entries)
        duplicate_set = set(id(entry) for entry, _ in duplicate_pairs)

        # Add a metadata marker to the extracted entries for duplicates.
        mod_entries = []
        for entry in new_entries:
            if id(entry) in duplicate_set:
                marked_meta = entry.meta.copy()
                marked_meta[DUPLICATE_META] = True
                entry = entry._replace(meta=marked_meta)
                duplicate_entries.append(entry)
            mod_entries.append(entry)
        new_entries = mod_entries

    return new_entries, duplicate_entries


def print_extracted_entries(entries, file, filename):
    """Print the entries for the given importer.

    Args:
      entries: A list of extracted entries.
      file: A file object to write to.
      filename: A filename object
    """
    print(HEADER, file=file)
    print('', file=file)
    print(SECTION.format(filename), file=file)
    print('', file=file)
    # Print out the entries.
    for entry in entries:
        # Check if this entry is a dup, and if so, comment it out.
        if DUPLICATE_META in entry.meta:
            meta = entry.meta.copy()
            meta.pop(DUPLICATE_META)
            entry = entry._replace(meta=meta)
            entry_string = textwrap.indent(printer.format_entry(entry), '; ')
        else:
            entry_string = printer.format_entry(entry)
        print(entry_string, file=file)
    print('', file=file)


def extract(importer,
            filename,
            entries=None,
            options_map=None,
            mindate=None,
            ascending=True):
    """Given an importer configuration, search for files that can be imported in the
    list of files or directories, run the signature checks on them, and if it
    succeeds, run the importer on the file.

    A list of entries for an existing ledger can be provided in order to perform
    de-duplication and a minimum date can be provided to filter out old entries.

    Args:
      importer: A configuration.
      filename: filename to be processed.
      output: A file object, to be written to.
      entries: A list of directives loaded from the existing file for the newly
        extracted entries to be merged in.
      options_map: The options parsed from existing file.
      mindate: Optional minimum date to output transactions for.
      ascending: A boolean, true to print entries in ascending order, false if
        descending is desired.
    """
    allow_none_for_tags_and_links = (
        options_map and options_map["allow_deprecated_none_for_tags_and_links"])

    # Import and process the file.
    try:
        new_entries, duplicate_entries = extract_from_file(
            filename,
            importer,
            existing_entries=entries,
            min_date=mindate,
            allow_none_for_tags_and_links=allow_none_for_tags_and_links)
    except Exception as exc:
        logging.error("Importer %s.extract() raised an unexpected error: %s",
                      importer.name(), exc)
        logging.error("Traceback: %s", traceback.format_exc())
        return []
    if not new_entries and not duplicate_entries:
        return []

    if not ascending:
        new_entries.reverse()

    return new_entries

def main():
    parser = argparse.ArgumentParser(description="Extract transactions from downloads")

    # TODO integrate these back into script_utils
    parser.add_argument('config', metavar='CONFIG_FILENAME',
                        help=('Importer configuration file. '
                              'This is a Python file with a data structure that '
                              'is specific to your accounts'))

    parser.add_argument('file', metavar='FILE',
                        default=None,
                        help='Filename to import')

    parser.add_argument(
        '-e', '-f', '--existing', '--previous',
        metavar='BEANCOUNT_FILE', default=None,
        help=('Beancount file or existing entries for de-duplication (optional)')
    )

    parser.add_argument(
        '-r', '--reverse', '--descending',
        action='store_const', dest='ascending', default=True, const=False,
        help='Write out the entries in descending order')

    parser.add_argument(
        '-g', '-s', '--guessing', '--suggestions',
        action='store_const', dest='ag_active', default=False, const=True,
        help='Provide suggestions'
    )

    parser.add_argument(
        '-p', '-t', '--prepopulate', '--train',
        action='store_const', dest='train', default=False, const=True,
        help='Train the account guesser using the existing beancount file'
    )

    args = parser.parse_args()

    # Check the existence of file.
    if args.file is None or not path.exists(args.file):
        parser.error("File does not exist: '{}'".format(args.file))

    # Load the ledger, if one is specified.
    if args.existing:
        entries, _, options_map = loader.load_file(args.existing)
    else:
        entries = None
        options_map = None

    # Import the configuration.
    mod = runpy.run_path(args.config)
    config = mod['CONFIG']

    new_entries = extract(
        config,
        path.abspath(args.file),
        entries=entries, options_map=options_map,
        mindate=None, ascending=args.ascending
    )
    accounts_dict = getters.get_dict_accounts(
        account_names=getters.get_accounts(entries))

    ag = guesser.AccountGuess() if args.ag_active else None
    if args.ag_active and args.train:
        for txn in data.filter_txns(entries):
            if txn.flag == flags.FLAG_OKAY:
                try:
                    # TODO fix using hardcoding
                    account = txn.postings[1].account
                    ag.add_txn(txn, account)
                except KeyError:
                    raise

    formatter = logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
    with io.StringIO() as curses_log:
        console_handler = logging.StreamHandler(curses_log)
        console_handler.setFormatter(formatter)
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        logger.addHandler(console_handler)
        try:
            curses.wrapper(select_account, new_entries, accounts_dict, ag=ag)
        except IndexError:
            print(curses_log.getvalue())
            raise
        print(curses_log.getvalue())

    print_extracted_entries(entries=new_entries, file=sys.stdout, filename=path.basename(args.file))

    return 0

if __name__ == "__main__":
    main()
