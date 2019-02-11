"""
Interactive account picker
"""
__copyright__ = "Copyright (C) 2018  Michael Droogleever"
__license__ = "MIT"

import time
import logging
import curses
from pprint import pformat
from curses import panel
from beancount.parser import printer
from beancount.ingest.interactive.guesser import AccountGuess


def no_root(nest_dict):
    """Get dict without root"""
    return {k: v for k, v in nest_dict.items() if k != '__root__'}

def is_root(nest_dict):
    return '__root__' in nest_dict and nest_dict['__root__']


class AccountSelector:
    """
    AccountSelector instance represents the nested account struct selections.
    One account is selected and navigation methods are provided.
    """
    def __init__(self, accounts_dict):
        super().__init__()
        self.accounts_dict = accounts_dict
        self.selected = None
        self.reset()

    def reset(self):
        """Reset state"""
        self.selected = [0]

    def _get_account(self):
        """Get account as selected"""
        names = []
        nest_dict = self.accounts_dict
        for idx in self.selected:
            keys = list(no_root(nest_dict))
            names.append(keys[idx])
            nest_dict = list(no_root(nest_dict).values())[idx]
        return ':'.join(names)
    def _get_selected(self):
        """Get selected"""
        return self.selected
    @property
    def account(self):
        return self._get_account()
    def set_account(self, account):
        """Set state given account"""
        account_list = account.split(':')
        nest_dict = self.accounts_dict
        selected = []
        for part in account_list:
            selected.append(list(no_root(nest_dict)).index(part))
            nest_dict = nest_dict[part]
        self.selected = selected
    def set_selected(self, selected):
        """Set state given selected"""
        self.selected = selected

    def prev_account(self):
        self.selected[-1] = max(self.selected[-1]-1, 0)
    def next_account(self):
        nest_dict = no_root(self._get_nested_dict_from_selected(self.selected[:-1]))
        self.selected[-1] = min(self.selected[-1]+1, len(nest_dict)-1)
    def prev_level(self):
        if len(self.selected) > 1:
            self.selected.pop()
    def next_level(self):
        nest_dict = self._get_nested_dict_from_selected(self.selected)
        if no_root(nest_dict):
            self.selected.append(0)

    def _get_nested_dict_from_selected(self, selected):
        """Get dict of selected accounts from selected"""
        nest_dict = self.accounts_dict
        for idx in selected:
            nest_dict = list(no_root(nest_dict).values())[idx]
        return nest_dict

    def get_nested_dict(self):
        """Get dict of selected accounts"""
        return self._get_nested_dict_from_selected(self.selected)


def select_account(stdscr, entries, accounts_dict, ag=None):
    """
    Curses entrypoint for selecting account.
    Iterates through the entries and executes a selection on each
    For each entry, a while loop waits for the user to select an account.

    Args:
      stdscr: stdscr
      entries: Entries to which need accounts selected.
      accounts_dict: Accounts available as a nested dict
      ag: AccountGuess object
    """

    logger = logging.getLogger(__name__)

    ag_active = True
    if ag is None:
        ag_active = False
        ag = AccountGuess()

    max_y, max_x = stdscr.getmaxyx()
    E_START = 3
    E_HEIGHT = 8
    A_START = E_START + E_HEIGHT + 1
    curses.curs_set(0)

    stdscr.addstr(0, 0, "Entries Editor", curses.A_BOLD + curses.A_UNDERLINE)
    stdscr.addstr(1, 0, "q: Quit    r: Save    w,a,s,d: Select account", curses.A_BOLD)

    # Create a panel per entry
    panels = []
    for entry in entries:
        newpanel = panel.new_panel(curses.newwin(E_HEIGHT, max_x-2, E_START, 0))
        newpanel.hide()
        panels.append(newpanel)

    account_win = curses.newwin(max_y-A_START, max_x, A_START, 0)

    stdscr.refresh()

    # Use exception to break out of UI
    class Quit(Exception): pass
    
    try:
        for entry, itempanel in zip(entries, panels):

            # Refresh
            itempanel.show()
            panel.update_panels()
            stdscr.refresh()


            account_selected = AccountSelector(accounts_dict)

            account_name = ag.get_account(entry)
            if ag_active and account_name is not None:
                account_selected.set_account(account_name)
                logger.debug("account_guess_used: %s, %s",
                             account_name, account_selected.selected)
            else:
                logger.debug("account_guess_notused: %s", account_name)
            while True:
                itempanel.window().clear()
                draw_txn(itempanel.window(), entry)
                draw_accounts(account_win, accounts_dict, account_selected)
                itempanel.window().refresh()
                keystr = itempanel.window().getkey()
                if keystr == 'q':
                    raise Quit
                if keystr == 'w':
                    account_selected.prev_account()
                if keystr == 's':
                    account_selected.next_account()
                if keystr == 'd':
                    account_selected.next_level()
                if keystr == 'a':
                    account_selected.prev_level()
                if keystr == 'r':
                    nest_dict = account_selected.get_nested_dict()
                    if is_root(nest_dict):
                        # TODO don't hard code posting to replace
                        account_name = account_selected.account
                        logger.debug("account_selected: %s", account_name)
                        entry.postings[1] = entry.postings[1]._replace(
                            account=account_name)
                        ag.add_txn(entry, account_name)
                        break
            draw_txn(itempanel.window(), entry)
            draw_account(account_win, account_name)
            itempanel.window().refresh()
            account_win.refresh()
            time.sleep(0.5)
            itempanel.hide()
    except Quit:
        pass
    # return entries

def draw_txn(win, entry):
    """
    Draw transaction
    """
    win.clear()
    win.addstr(1, 2, f"Transaction:")
    entry_str = printer.format_entry(entry)
    for idx, line in enumerate(entry_str.splitlines()):
        win.addstr(2+idx, 2, line)
    win.box()

def draw_account(win, account_name):
    """
    Draw account
    """
    win.clear()
    win.addstr(1, 0, f"Account:")
    win.addstr(2, 0, account_name)

def draw_accounts(win, accounts_dict, account_selected):
    """
    Draw accounts
    """
    win.clear()
    START = 1
    win.addstr(START-1, 0, f"Accounts:", curses.A_BOLD+curses.A_UNDERLINE)
    nest_dict = accounts_dict
    maxlevel = 0
    for nestlevel, keyidx in enumerate(account_selected.selected):
        maxlevel = nestlevel
        for idx, acckey in enumerate(no_root(nest_dict)):
            attr = curses.A_NORMAL
            if idx == keyidx:
                attr += curses.A_BOLD
                if nestlevel == len(account_selected.selected)-1:
                    attr += curses.A_STANDOUT
            if is_root(nest_dict[acckey]):
                attr += curses.A_UNDERLINE
            win.addstr(START+idx, 2+18*nestlevel, f"{acckey:<16}:", attr)
        nest_dict = list(no_root(nest_dict).values())[keyidx]

    for idx, acckey in enumerate(no_root(nest_dict)):
        attr = curses.A_NORMAL
        if is_root(nest_dict[acckey]):
            attr += curses.A_UNDERLINE
        win.addstr(START+idx, 2+18*(maxlevel+1), f"{acckey:<16}:", attr)
    win.refresh()
