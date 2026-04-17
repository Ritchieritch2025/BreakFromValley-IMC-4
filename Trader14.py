"""
Trader14 — OSMIUM with hardcoded FV = 10000.
PEPPER: baseline buy-and-hold.

Observation from the 3-day price plot: OSMIUM oscillates tightly around 10000
with no drift. Fair value is constant. Using mid as FV made the take loop dead
(ask is never below mid on a snapshot). Using 10000 as FV resurrects it:
whenever mid drifts below 10000 we buy the ask, whenever mid drifts above
10000 we sell the bid — at a guaranteed edge against true FV.

Make orders also move with the constant FV: bid 9999, ask 10001 (straightforward).
"""
import json
from datamodel import Order, TradingState

FV = 10000


class Trader:
    def __init__(self):
        self.position_limits = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}

    def run(self, state: TradingState):
        result = {}
        trader_data = {}
        if state.traderData:
            try:
                trader_data = json.loads(state.traderData)
            except (json.JSONDecodeError, TypeError):
                trader_data = {}
        for product in state.order_depths:
            od = state.order_depths[product]
            pos = state.position.get(product, 0)
            lim = self.position_limits.get(product, 80)
            if product == "ASH_COATED_OSMIUM":
                result[product] = self.trade_osmium(product, od, pos, lim)
            elif product == "INTARIAN_PEPPER_ROOT":
                result[product] = self.trade_pepper(product, od, pos, lim)
            else:
                result[product] = []
        return result, 0, json.dumps(trader_data)

    def trade_osmium(self, product, order_depth, position, limit):
        orders = []
        buy_vol = 0
        sell_vol = 0

        # TAKE: buy any ask strictly below FV
        for ask_price in sorted(order_depth.sell_orders.keys()):
            if ask_price >= FV:
                break
            ask_qty = abs(order_depth.sell_orders[ask_price])
            can_buy = limit - position - buy_vol
            if can_buy <= 0:
                break
            qty = min(ask_qty, can_buy)
            orders.append(Order(product, ask_price, qty))
            buy_vol += qty

        # TAKE: sell any bid strictly above FV
        for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
            if bid_price <= FV:
                break
            bid_qty = order_depth.buy_orders[bid_price]
            can_sell = limit + position - sell_vol
            if can_sell <= 0:
                break
            qty = min(bid_qty, can_sell)
            orders.append(Order(product, bid_price, -qty))
            sell_vol += qty

        # MAKE: post remaining capacity at FV±1
        rem_buy = limit - position - buy_vol
        if rem_buy > 0:
            orders.append(Order(product, FV - 1, rem_buy))
        rem_sell = limit + position - sell_vol
        if rem_sell > 0:
            orders.append(Order(product, FV + 1, -rem_sell))

        return orders

    def trade_pepper(self, product, order_depth, position, limit):
        orders = []
        if not order_depth.sell_orders:
            return orders
        can_buy = limit - position
        if can_buy <= 0:
            return orders
        for ask_price in sorted(order_depth.sell_orders.keys()):
            ask_qty = abs(order_depth.sell_orders[ask_price])
            qty = min(ask_qty, can_buy)
            orders.append(Order(product, ask_price, qty))
            can_buy -= qty
            if can_buy <= 0:
                break
        return orders
