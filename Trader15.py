"""
Trader15 — OSMIUM: keep baseline's penny-jump MAKE (good edge),
                    but use hardcoded FV=10000 for TAKE/FLATTEN (resurrects dead code).
PEPPER: baseline buy-and-hold.

Trader14 proved the take logic works (62 new take fills) but sacrificed make
edge by quoting at 9999 fixed. Baseline's make earns ~7 edge/share via penny
jump, which swamped the take gains.

Fix: make at penny-jump (preserve 7 edge) + take on sub-FV asks (add ~280 PnL).
Net expected: baseline 2337 + take alpha ≈ 2600+.
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
        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders
        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        buy_vol = 0
        sell_vol = 0

        # TAKE against hardcoded FV=10000 (what was dead with fair=mid)
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

        # FLATTEN at FV when the other side is sitting there
        if position > 0 and order_depth.buy_orders.get(FV, 0) > 0:
            qty = min(order_depth.buy_orders[FV], limit + position - sell_vol, position)
            if qty > 0:
                orders.append(Order(product, FV, -qty))
                sell_vol += qty
        elif position < 0 and order_depth.sell_orders.get(FV, 0) != 0:
            qty = min(abs(order_depth.sell_orders[FV]), limit - position - buy_vol, -position)
            if qty > 0:
                orders.append(Order(product, FV, qty))
                buy_vol += qty

        # MAKE with penny-jump (baseline edge logic)
        buy_price = min(FV - 1, best_bid + 1)
        sell_price = max(FV + 1, best_ask - 1)
        skew = int((position / limit) * 3)
        buy_price -= skew
        sell_price -= skew
        buy_price = min(buy_price, FV - 1)
        sell_price = max(sell_price, FV + 1)

        rem_buy = limit - position - buy_vol
        if rem_buy > 0:
            orders.append(Order(product, buy_price, rem_buy))
        rem_sell = limit + position - sell_vol
        if rem_sell > 0:
            orders.append(Order(product, sell_price, -rem_sell))

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
