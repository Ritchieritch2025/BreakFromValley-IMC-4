"""
Trader16_osmium — OSMIUM only, pure scalp (take all sub-FV asks, take all super-FV bids).
No PEPPER logic. Empty orders for any other product.
"""
import json
from datamodel import Order, TradingState

FV = 10000


class Trader:
    def __init__(self):
        self.position_limits = {"ASH_COATED_OSMIUM": 80}

    def run(self, state: TradingState):
        result = {}
        trader_data = {}
        if state.traderData:
            try:
                trader_data = json.loads(state.traderData)
            except (json.JSONDecodeError, TypeError):
                trader_data = {}

        for product in state.order_depths:
            if product == "ASH_COATED_OSMIUM":
                od = state.order_depths[product]
                pos = state.position.get(product, 0)
                result[product] = self.trade_osmium(product, od, pos, 80)
            else:
                result[product] = []

        return result, 0, json.dumps(trader_data)

    def trade_osmium(self, product, order_depth, position, limit):
        orders = []
        buy_vol = 0
        sell_vol = 0

        # Buy every ask strictly below FV
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

        return orders
