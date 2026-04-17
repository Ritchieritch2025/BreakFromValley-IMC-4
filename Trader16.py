"""
Trader16 — OSMIUM: pure scalp, NO make orders.
PEPPER: baseline buy-and-hold.

Acts on the observation that the book constantly offers sub-FV asks and
super-FV bids. Every tick:
  - buy every ask < FV (all levels, not just best)
  - sell every bid > FV (all levels)
  - NO resting make orders at all

If this beats Trader 15 (2472), our makes were hurting by consuming capacity.
If it loses, makes carry most of the PnL and we should go back to layered
making. Either outcome is information.
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

        # Buy every ask strictly below FV (pure scalp)
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

        # Sell every bid strictly above FV
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

        # No make orders. Pure scalping only.
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
