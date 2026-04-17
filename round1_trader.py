"""
Round 1 Trader

ASH_COATED_OSMIUM: 围绕10000波动, 自相关-0.495, 类似EMERALDS
INTARIAN_PEPPER_ROOT: 每天稳定涨~1000, 自相关-0.501, 有趋势
"""
import json
from datamodel import Order, TradingState


class Trader:
    def __init__(self):
        self.position_limits = {
            "ASH_COATED_OSMIUM": 80,
            "INTARIAN_PEPPER_ROOT": 80,
        }

    def run(self, state: TradingState):
        result = {}
        trader_data = {}
        if state.traderData:
            try:
                trader_data = json.loads(state.traderData)
            except (json.JSONDecodeError, TypeError):
                trader_data = {}

        for product in state.order_depths:
            order_depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.position_limits.get(product, 80)

            if product == "ASH_COATED_OSMIUM":
                orders = self.trade_osmium(product, order_depth, position, limit)
            elif product == "INTARIAN_PEPPER_ROOT":
                orders = self.trade_pepper(product, order_depth, position, limit)
            else:
                orders = []

            result[product] = orders

        return result, 0, json.dumps(trader_data)

    def trade_osmium(self, product, order_depth, position, limit):
        """
        ASH_COATED_OSMIUM — 围绕10000, 和EMERALDS一样的做市逻辑
        数据: 每天avg=10000, range=46, 自相关-0.495
        """
        orders = []

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid = (best_bid + best_ask) / 2

        # FV用mid (实验验证过mid最准)
        fair = mid
        fair_int = int(round(fair))

        buy_vol = 0
        sell_vol = 0

        # Take
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

        # Flatten at FV
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

        # Make: penny jump + skew
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
        """
        INTARIAN_PEPPER_ROOT — 纯buy and hold
        每tick涨0.1, 买满80就不动
        """
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
