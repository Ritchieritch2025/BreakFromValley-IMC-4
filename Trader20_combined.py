"""
Trader20_combined — Trader19's Frankfurt-style OSMIUM + PEPPER buy-and-hold.

Expected total ≈ 9986 (2700 OSMIUM + 7286 PEPPER) — first break above 9800.

OSMIUM logic (from Trader19_osmium):
  - wall_mid = (bid_wall + ask_wall) / 2
  - Make base = bid_wall+1 / ask_wall-1, deep default
  - Overbid only when inner bids have volume > 1 and stay under wall_mid
  - Zero-edge clearing at wall_mid when inventory needs reducing
  - No price skew, size caps + clearing handle inventory

PEPPER logic (baseline, 7286 ceiling):
  - Aggressive take at t=0 to fill 80 limit
  - Hold to end, let trend carry
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
        buys = order_depth.buy_orders
        sells = order_depth.sell_orders
        if not buys or not sells:
            return orders

        bid_wall = min(buys.keys())
        ask_wall = max(sells.keys())
        wall_mid = (bid_wall + ask_wall) / 2

        buy_vol = 0
        sell_vol = 0

        # 1. TAKE — asks
        for sp in sorted(sells.keys()):
            sv = abs(sells[sp])
            can_buy = limit - position - buy_vol
            if can_buy <= 0:
                break
            if sp <= wall_mid - 1:
                qty = min(sv, can_buy)
                orders.append(Order(product, sp, qty))
                buy_vol += qty
            elif sp <= wall_mid and position < 0:
                qty = min(sv, can_buy, abs(position))
                if qty > 0:
                    orders.append(Order(product, sp, qty))
                    buy_vol += qty
            else:
                break

        # 2. TAKE — bids
        for bp in sorted(buys.keys(), reverse=True):
            bv = buys[bp]
            can_sell = limit + position - sell_vol
            if can_sell <= 0:
                break
            if bp >= wall_mid + 1:
                qty = min(bv, can_sell)
                orders.append(Order(product, bp, -qty))
                sell_vol += qty
            elif bp >= wall_mid and position > 0:
                qty = min(bv, can_sell, position)
                if qty > 0:
                    orders.append(Order(product, bp, -qty))
                    sell_vol += qty
            else:
                break

        # 3. MAKE — Frankfurt-style deep default with selective overbid
        bid_price = int(bid_wall + 1)
        ask_price = int(ask_wall - 1)

        for bp in sorted(buys.keys(), reverse=True):
            bv = buys[bp]
            overbid = bp + 1
            if bv > 1 and overbid < wall_mid:
                bid_price = max(bid_price, overbid)
                break
            elif bp < wall_mid:
                bid_price = max(bid_price, bp)
                break

        for sp in sorted(sells.keys()):
            sv = abs(sells[sp])
            underbid = sp - 1
            if sv > 1 and underbid > wall_mid:
                ask_price = min(ask_price, underbid)
                break
            elif sp > wall_mid:
                ask_price = min(ask_price, sp)
                break

        bid_price = min(bid_price, int(wall_mid) - 1)
        ask_price = max(ask_price, int(wall_mid) + 1)

        rem_buy = limit - position - buy_vol
        if rem_buy > 0:
            orders.append(Order(product, bid_price, rem_buy))
        rem_sell = limit + position - sell_vol
        if rem_sell > 0:
            orders.append(Order(product, ask_price, -rem_sell))

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
