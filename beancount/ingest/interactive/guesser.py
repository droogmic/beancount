"""
Interactive account picker.
"""
__copyright__ = "Copyright (C) 2018  Michael Droogleever"
__license__ = "MIT"

import logging
from pprint import pformat
from itertools import chain
from beancount.core.interpolate import AUTOMATIC_META, AUTOMATIC_RESIDUAL, AUTOMATIC_TOLERANCES

EXCLUSIONS = ('filename', 'lineno', AUTOMATIC_META, AUTOMATIC_RESIDUAL, AUTOMATIC_TOLERANCES)


def increment_dict(target_dict, key, increment):
    target = target_dict.setdefault(key, 0)
    target_dict[key] = target + increment

def item_gen(txn):
    narr_items = txn.narration.split()
    try:
        payee_items = txn.payee.split()
    except AttributeError:
        payee_items = []
    meta_vals = (val for key, val in txn.meta.items() if key not in EXCLUSIONS)
    return chain(narr_items, payee_items, meta_vals)


class AccountGuess:
    """
    AccountGuess
    Get best match Account
    """
    def __init__(self):
        super().__init__()
        self.save_dict = {}
        self.logger = logging.getLogger(__name__)

    def add_txn(self, txn, account_name):
        self.logger.debug("add_txn items:\n%s", list(item_gen(txn)))
        for item in item_gen(txn):
            guess_item = self.save_dict.setdefault(item, GuessItem())
            guess_item.add(account_name)

    def get_account(self, txn):
        votes = {}
        for item in item_gen(txn):
            guess_item = self.save_dict.get(item)
            if guess_item:
                item_dict = guess_item.get()
                self.logger.debug('guess_item - %s:\n%s',
                                  item, pformat(item_dict))
                for acc, itemvote in item_dict.items():
                    increment_dict(votes, acc, itemvote*len(item))
        if votes:
            self.logger.debug('get_account - votes:\n%s', pformat(votes))
            # self.logger.debug('%s\n%s', "get_account save_dict", pformat(self.save_dict))
            return max(votes, key=votes.get)
        return None


class GuessItem:
    """
    GuessItem
    Get best match item
    """
    def __init__(self):
        super().__init__()
        self.account_dict = {}
    def add(self, account):
        increment_dict(self.account_dict, account, 1)
    def get(self):
        return {account: self.get_weight(account) for account in self.account_dict}
    def get_weight(self, selected_account):
        selected_votes = self.account_dict[selected_account]
        weight = selected_votes / sum(self.account_dict.values())
        return weight*weight #Devalue non-exact matches
