"""
Trader13 — PEPPER: sell-at-resistance only. Accumulate to 80, then post a passive
ask at best_ask-1 (size 5). Do NOT attempt to rebuy — just let the trend carry the
remaining 75+ position forward. Converts some paper gain into realized before any
possible reversal.
OSMIUM: baseline MM.
Hypothesis: simpler than Trader12, lower risk. If the scalp fills we realize +spread
on 5 units per fill without the adverse-selection risk of re-bidding.
"""
import json
from datamodel import Order, TradingState

SCALP_SIZE = 5
POSITION_FLOOR = 75


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
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid = (best_bid + best_ask) / 2
        fair = mid
        fair_int = int(round(fair))
        buy_vol = 0
        sell_vol = 0
        for ask_price in sorted(order_depth.sell_orders.keys()):
            if ask_price >= fair:
                break
            ask_qty = abs(order_depth.sell_orders[ask_price])
            can_buy = limit - position - buy_vol
            if can_buy <= 0:
                break
            qty = min(ask_qty, can_buy)
            orders.append(Order(product, ask_price, qty))
            buy_vol += qty
        for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
            if bid_price <= fair:
                break
            bid_qty = order_depth.buy_orders[bid_price]
            can_sell = limit + position - sell_vol
            if can_sell <= 0:
                break
            qty = min(bid_qty, can_sell)
            orders.append(Order(product, bid_price, -qty))
            sell_vol += qty
        if position > 0 and order_depth.buy_orders.get(fair_int, 0) > 0:
            qty = min(order_depth.buy_orders[fair_int], limit + position - sell_vol, position)
            if qty > 0:
                orders.append(Order(product, fair_int, -qty))
                sell_vol += qty
        elif position < 0 and order_depth.sell_orders.get(fair_int, 0) != 0:
            qty = min(abs(order_depth.sell_orders[fair_int]), limit - position - buy_vol, -position)
            if qty > 0:
                orders.append(Order(product, fair_int, qty))
                buy_vol += qty
        buy_price = min(fair_int - 1, best_bid + 1)
        sell_price = max(fair_int + 1, best_ask - 1)
        skew = int((position / limit) * 3)
        buy_price -= skew
        sell_price -= skew
        buy_price = min(buy_price, fair_int - 1)
        sell_price = max(sell_price, fair_int + 1)
        rem_buy = limit - position - buy_vol
        if rem_buy > 0:
            orders.append(Order(product, buy_price, rem_buy))
        rem_sell = limit + position - sell_vol
        if rem_sell > 0:
            orders.append(Order(product, sell_price, -rem_sell))
        return orders

    def trade_pepper(self, product, order_depth, position, limit):
        orders = []
        if not order_depth.sell_orders or not order_depth.buy_orders:
            return orders
        best_ask = min(order_depth.sell_orders.keys())
        if position < limit:
            can_buy = limit - position
            for ask_price in sorted(order_depth.sell_orders.keys()):
                ask_qty = abs(order_depth.sell_orders[ask_price])
                qty = min(ask_qty, can_buy)
                orders.append(Order(product, ask_price, qty))
                can_buy -= qty
                if can_buy <= 0:
                    break
            return orders
        # position == limit: sell at resistance only (no rebuy)
        sell_qty = min(SCALP_SIZE, position - POSITION_FLOOR)
        if sell_qty > 0:
            orders.append(Order(product, best_ask - 1, -sell_qty))
        return orders
