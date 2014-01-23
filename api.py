#!/usr/bin/env python
#
#

from pprint import pprint, pformat

from decimal import Decimal
import requests
from requests.exceptions import RequestException
import json
import base64
import hmac
import hashlib
import time
import logging

logger = logging.getLogger('bitfinex_api')
logger.setLevel(logging.DEBUG)


def main():
    bfx = Bitfinex(secret="", key="")
    print(bfx.lendbook())

if __name__ == '__main__':
    main()


__all__ = ['BFXAPI', 'Bitfinex']

_ACCT_TYPES = set(['exchange', 'deposit', 'trading'])


# class BFXLoanAPI(object):
#
#     def __init__(self, secret=None, key=None):
#         pass
#
#     def lending_balances(self):
#         """Returns info on borrowed/lent assets as well as free assets"""
#
#     def lending_orderbook(self):
#         """Returns order book"""
#
#     def place_loan_ask(self, amount, rate, currency):
#         """Put in order to lend"""
#
#     def place_loan_bid(self, amount, rate, currency):
#         """Put in order to borrow"""
#
#     def cancel_loan_order(self):
#         """Will need to pass some sort of identifier"""


class Bitfinex(object):
    """"""
    # TODO: add new offer (lend/borrow), past trades, active positions, active credits, rest of lending/borrowing stuff
    # todo: convert the %/365days on lends to %/day?
    # todo: massage data into more useful form than dicts???
        # if nothing else, add docs for returned info format
    # todo: make sure secret/key is provided before allowing authenticated commands to be used

    _API_DOMAIN = 'api.bitfinex.com'
    _API_PROTOCOL = 'https'
    _API_VERSION = 'v1'
    if _API_PROTOCOL not in {'http', 'https'} or _API_VERSION not in {'v1'}:
        raise ValueError('Invalid component used in constructing Bitfinex API URL: protocol=' + _API_PROTOCOL +
                         ', version=' + _API_VERSION)
    API_URL = _API_PROTOCOL + '://' + _API_DOMAIN + '/' + _API_VERSION + '/'

    # todo verify vs these sets, set _PAIRS using Bitfinex.symbols() and also rename that to pairs()

    # list of supported and unsupported commands:
    # All:
    #       ticker, today, lendbook, book (orderbook), trades, lends, symbols (pairs), order/new, order/new/multi,
    #       order/cancel, order/cancel/multi, order/cancel/all, order/cancel/replace, order/status, orders, positions,
    #       mytrades (history), offer/new, offer/cancel, offer/status, offers, credits, balances.
    # Supported:
    #       ticker, today, lendbook, book, trades, lends, symbols, order/new, order/cancel, order/status,
    #       orders, balances.
    # todo/currently unsupported:
    #       order/new/multi, order/cancel/multi, order/cancel/all, order/cancel/replace,
    #       positions, mytrades, offer/new, offer/cancel, offer/status, offers, credits.

    _CURRENCIES = set(['btc', 'ltc', 'usd'])
    _PAIRS = set(['btcusd', 'ltcusd', 'ltcbtc'])

    # commands that need a pair parameter and not a currency
    _PAIR_CMDS = set(['ticker', 'today', 'book', 'trades', 'order/new'])
    # commands that need a currency parameter and not a pair
    _CURRENCY_CMDS = set(['lendbook', 'lends'])
    _OTHER_CMDS = set(['symbols', 'order/cancel', 'order/status', 'orders', 'balances'])
    # commands requiring authentication to use
    _AUTHED_CMDS = set(['order/new', 'order/cancel', 'order/status', 'orders', 'balances'])

    # full list of commands usable on Bitfinex
    COMMANDS = (_CURRENCY_CMDS.union(_PAIR_CMDS)).union(_OTHER_CMDS)

    JSON_DECIMAL_KEYS = set(['amount', 'ask', 'available', 'bid', 'executed_amount', 'high', 'last_price',
                             'low', 'mid', 'original_amount', 'price', 'remaining_amount', 'timestamp',
                             'volume', 'rate', 'amount_lent'])

    def __init__(self, secret=None, key=None):
        self.secret = secret
        self.key = key
        # Check whether pair list is up to date
        # TODO make this check optional?
        pair_list = self.pairs()
        if pair_list != [] and Bitfinex._PAIRS != set(pair_list):
            logger.warning("List of known pair types is out of date: " + str(Bitfinex._PAIRS) +
                           ' vs retrieved ' + str(pair_list))
        elif pair_list is []:
            logger.warning("Could not verify pair list: received empty list.")

    def _send_request(self, command, symbol=None, payload=None):
        """Private method to execute requests with error handling and other sanity checks."""

        # Make sure inputs are correct:
        # 1. Command can only be a str
        if type(command) is not str:
            raise ValueError("Bad command value (non-string) passed to bfx api: " + command)
        # 2. Symbol can only be a str or NoneType
        elif symbol is not None and type(symbol) is not str:
            raise ValueError("Bad symbol value (non-string/None) passed to bfx api: " + symbol)
        # 3. Payload can only be a dict or NoneType
        elif payload is not None and type(payload) is not dict:
            raise ValueError("Bad payload value (non-dict) passed to bfx api: " + payload)

        if command in Bitfinex.COMMANDS:
            if command in Bitfinex._OTHER_CMDS:
                # no symbol (pair/currency) needed for api command
                cmd_url = Bitfinex.API_URL + command + '/'
            elif command in Bitfinex._CURRENCY_CMDS and symbol in Bitfinex._CURRENCIES:
                cmd_url = Bitfinex.API_URL + command + '/' + symbol
            elif command in Bitfinex._PAIR_CMDS and symbol in Bitfinex._PAIRS:
                cmd_url = Bitfinex.API_URL + command + '/' + symbol
            else:
                raise ValueError('Invalid command and symbol (currency or pair) combination for Bitfinex command: ' +
                                 command + ' with symbol ' + symbol)
        else:
            raise ValueError('Bitfinex API command not supported: ' + command)

        try:
            headers = None
            # todo disable verification of ssl again???
            # todo check validity of command + (pair || currency)
            if payload is not None and payload is not {}:
                if command in Bitfinex._AUTHED_CMDS:
                    headers = self._sign(True, payload)
                else:
                    headers = self._sign(False, payload)

            response = requests.get(cmd_url, verify=True, headers=headers, timeout=1)
            response_json = response.json()
        except ValueError as e:
            logger.warning('Error reading response to a Bitfinex API command with URL ' + cmd_url +
                           ' and payload ' + pformat(payload) + ' - ' + str(e))
        except RequestException as e:
            logger.warning('Error in response to a Bitfinex API command: ' + str(e))
        else:
            return bfx_decimalize(response_json)
        return {}

    def ticker(self, pair="btcusd"):
        """Returns a dict with keys of mid, bid, ask, last_price, and timestamp.
        No authentication needed.
        """
        return self._send_request(self, 'ticker', pair)

    def today(self, pair="btcusd"):
        """Returns a dict with keys of high, low, and volume.
        No authentication needed.
        """
        return self._send_request('today', pair)

    def orderbook(self, pair="btcusd", limit_bids=50, limit_asks=50):
        """ Get the orderbook.
        Arguments:
        pair       -- the pair to look up
        limit_bids -- maximum number of bids to retrieve (default 50)
        limit_asks -- maximum number of asks to retrieve (default 50)

        Returns a dict with keys of bids and asks, both containing
         a list of dicts with keys of price, amount, and timestamp.
        No authentication needed.
        """

        # payload options:
        #   limit_bids (int): Optional. Limit the number of bids returned.
        #       May be 0 in which case the array of bids is empty. Default is 50.
        #   limit_asks (int): Optional. Limit the number of asks returned.
        #       May be 0 in which case the array of asks is empty. Default is 50.
        payload = {}
        if limit_bids != 50:
            payload['limit_bids'] = limit_bids
        if limit_asks != 50:
            payload['limit_asks'] = limit_asks
        return self._send_request('book', pair, payload)

    def trades(self, pair="btcusd", limit_trades=50, timestamp=None):
        """ Get recent trades.
        Arguments:
        pair         -- the pair to look up
        limit_trades -- maximum number of trades to retrieve (default 50)
        timestamp    -- only show trades at or after this timestamp

        Returns a list of most recent trades, in the form of a list of dicts
        with keys of amount, exchange (bitfinex or bitstamp), price, and timestamp.
        No authentication required.
        """
        # payload options:
        #   timestamp (time): Optional. Only show trades at or after this timestamp.
        #   limit_trades (int): Optional. Limit the number of trades returned. Must be >= 1. Default is 50.
        payload = {}
        if limit_trades != 50:
            payload['limit_trades'] = limit_trades
        if timestamp is not None:
            payload['timestamp'] = timestamp
        return self._send_request('trades', pair, payload)

    def lendbook(self, currency="usd", limit_bids=50, limit_asks=50):
        """Get the lendbook, the list of active loan bids and asks.
        Arguments:
        currency   -- the currency to look up
        limit_bids -- maximum number of bids to retrieve (default 50)
        limit_asks -- maximum number of asks to retrieve (default 50)

        Returns a dict with keys of bids and asks, each containing a list of dicts
        with keys amount, period, rate (per 365 days), and timestamp.
        No authentication required.
        """
        # payload options:
        #   limit_bids (int): Optional. Limit the number of bids (loan demands) returned.
        #       May be 0 in which case the array of bids is empty. Default is 50.
        #   limit_asks (int): Optional. Limit the number of asks (loan offers) returned.
        #       May be 0 in which case the array of asks is empty. Default is 50
        payload = {}
        if limit_bids != 50:
            payload['limit_bids'] = limit_bids
        if limit_asks != 50:
            payload['limit_asks'] = limit_asks
        return self._send_request('lendbook', currency, payload)

    def lends(self, currency="usd", limit_lends=50, timestamp=None):
        """ Get recent lends.
        Arguments:
        currency    -- the currency to look up
        limit_lends -- maximum number of lends to retrieve (default 50)
        timestamp   -- only show lends at or after this timestamp
        Returns most recently completed loans, in the form of a list of dicts
        with keys of amount_lent, rate, and timestamp.
        No authentication required.
        """
        # payload options:
        #   timestamp (time): Optional. Only show trades at or after this timestamp.
        #   limit_lends (int): Optional. Limit the number of lends returned. Must be >= 1. Default is 50.
        payload = {}
        if limit_lends != 50:
            payload['limit_lends'] = limit_lends
        if timestamp is not None:
            payload['timestamp'] = timestamp
        return self._send_request('lends', currency, payload)

    def pairs(self):
        """Returns a list of currency pairs that can be used on Bitfinex"""
        return self._send_request('symbols')

    def order_new(self, amount, price, side, trade_type, pair='btcusd', exchange='all', hidden=False):
        """ Creates a new order.
        Arguments:
        pair       -- pair to open trade on
        amount     -- amount of trade
        price      -- price of trade
        exchange   -- which exchange - bitfinex, bitstamp, or all
        side       -- bid or ask
        trade_type -- for margin trades: limit, market, stop, trailing stop.
                        for exchange trades: exchange limit, exchange market, exchange stop, exchange trailing stop.
        hidden     -- whether to hide the trade. True or False.

        Requires authentication.
        """
        payload = dict()
        payload['request'] = '/' + Bitfinex._API_VERSION + '/order/new'
        payload['nonce'] = str(time.time() * 100000)

        payload['symbol'] = pair
        payload['amount'] = amount
        payload['price'] = price
        payload['side'] = side
        payload['type'] = trade_type
        # todo: only allow hidden when it meets the minimum requirement of 100btc or 100ltc (fee 0.001)
        payload['is_hidden'] = hidden
        payload['exchange'] = exchange
        # todo: fix all these - need to post and not get????
        return self._send_request('order/new', payload=payload)
        #headers = self._sign(True, payload)
        #r = requests.post("https://"+_BITFINEX+"/v1/order/new", headers=headers, verify=False)
        #return decimalize(r.json(), _DECIMAL_KEYS)

    def order_cancel(self, order_id):
        """ Cancels an order.
        Arguments:
        order_id -- ID of the order to cancel, as provided by /order/new

        Requires authentication.
        """
        payload = dict()
        payload['order_id'] = order_id
        payload['request'] = '/' + Bitfinex._API_VERSION + '/order/cancel'
        payload['nonce'] = str(time.time() * 100000)
        return self._send_request('order/cancel', payload=payload)

    def order_status(self, order_id):
        """ Get the status of an order.
        Arguments:
        order_id -- ID of the order to check status on, as provided by /order/new

        Requires authentication.
        """
        payload = dict()
        payload['order_id'] = order_id
        payload['request'] = '/' + Bitfinex._API_VERSION + '/order/status'
        payload['nonce'] = str(time.time() * 100000)
        return self._send_request('order/status', payload=payload)

    def orders(self):
        """ Returns a list of all active orders.

        Requires authentication
        """
        payload = dict()
        payload['request'] = '/' + Bitfinex._API_VERSION + '/orders'
        payload["nonce"] = str(time.time() * 100000)
        return self._send_request('orders', payload=payload)

    def balances(self):
        """Get current balances in all wallets (exchange/trading/deposit) of all currencies (currently btc/ltc/usd).

        Requires authentication.
        """
        payload = dict()
        payload['request'] = '/' + Bitfinex._API_VERSION + '/balances'
        payload["nonce"] = str(time.time() * 100000)
        return self._send_request('balances', payload=payload)

    # Private
    def _sign(self, should_sign, d):
        j = json.dumps(undecimalize(d))
        data = base64.standard_b64encode(j.encode('utf-8'))

        if should_sign:
            if self.secret is None:
                #todo error handling all over in this code
                print('problem signing: no secret set')
                raise Exception
            h = hmac.new(self.secret.encode('utf-8'), data, hashlib.sha384)
            signature = h.hexdigest()

            return {
                "X-BFX-APIKEY": self.key,
                "X-BFX-SIGNATURE": signature,
                "X-BFX-PAYLOAD": data,
            }
        else:
            return {
                "X-BFX-PAYLOAD": data,
            }


def bfx_decimalize(obj):
    return decimalize(obj, Bitfinex.JSON_DECIMAL_KEYS)


def decimalize(obj, keys):
    """Utility to convert string formatted numbers in JSON objects into Decimals"""
    if isinstance(obj, list):
        return [decimalize(xs, keys) for xs in obj]
    if not isinstance(obj, dict):
        return obj

    def to_decimal(k, val):
        if val is None:
            return None
        if isinstance(val, list):
            return [decimalize(ys, keys) for ys in val]
        if k in keys:
            return Decimal(val)
        return val
    return {k: to_decimal(k, obj[k]) for k in obj}


def undecimalize(obj):
    """Utility to convert Decimals in JSON objects back to strings"""
    if isinstance(obj, list):
        return map(undecimalize, obj)
    if not isinstance(obj, dict):
        return obj

    #print obj
    def from_decimal(val):
        if isinstance(val, Decimal):
            return str(val)
        return val
    return {k: from_decimal(obj[k]) for k in obj}