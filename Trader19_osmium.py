"""
Trader19_osmium — adopt Frankfurt Hedgehogs' static-asset approach.

Four differences vs our Trader18:
  1. wall_mid (midpoint of outermost visible bid/ask) as FV reference,
     instead of fixed FV or raw mid.
  2. Make base price = bid_wall + 1 / ask_wall - 1  (deep default),
     NOT best_bid + 1 (which drags us into low-edge territory when
     inner bots are tight).
  3. Overbidding only when an inner bid has volume > 1 (real order,
     not dust) AND overbid stays strictly under wall_mid.
  4. Zero-edge clearing at wall_mid: when short, take asks at wall_mid
     to flatten; when long, sell to bids at wall_mid. No PnL on the
     trade itself but frees position capacity (~+3% per Linear Utility).

No price skew. Frankfurt relies on size caps + clearing for inventory,
not price bias.
"""
import json
from datamodel import Order, TradingState

PRODUCT = "ASH_COATED_OSMIUM"
LIMIT = 80


class Trader:
    def __init__(self):
        self.position_limits = {PRODUCT: LIMIT}

    def run(self, state: TradingState):
        result = {}
        trader_data = {}
        if state.traderData:
            try:
                trader_data = json.loads(state.traderData)
            except (json.JSONDecodeError, TypeError):
                trader_data = {}

        for product in state.order_depths:
            if product == PRODUCT:
                od = state.order_depths[product]
                pos = state.position.get(product, 0)
                result[product] = self.trade(product, od, pos)
            else:
                result[product] = []

        return result, 0, json.dumps(trader_data)

    def trade(self, product, order_depth, position):
        orders = []
        buys = order_depth.buy_orders   # price -> +vol
        sells = order_depth.sell_orders # price -> -vol

        if not buys or not sells:
            return orders

        bid_wall = min(buys.keys())
        ask_wall = max(sells.keys())
        wall_mid = (bid_wall + ask_wall) / 2

        buy_vol = 0
        sell_vol = 0

        # ================================================================
        # 1. TAKING — ask side (we buy)
        # ================================================================
        for sp in sorted(sells.keys()):
            sv = abs(sells[sp])
            can_buy = LIMIT - position - buy_vol
            if can_buy <= 0:
                break
            if sp <= wall_mid - 1:
                # edge >= 1: take it
                qty = min(sv, can_buy)
                orders.append(Order(product, sp, qty))
                buy_vol += qty
            elif sp <= wall_mid and position < 0:
                # zero-edge clearing: we're short, take to flatten
                qty = min(sv, can_buy, abs(position))
                if qty > 0:
                    orders.append(Order(product, sp, qty))
                    buy_vol += qty
            else:
                break  # asks above this point have no edge

        # ================================================================
        # 2. TAKING — bid side (we sell)
        # ================================================================
        for bp in sorted(buys.keys(), reverse=True):
            bv = buys[bp]
            can_sell = LIMIT + position - sell_vol
            if can_sell <= 0:
                break
            if bp >= wall_mid + 1:
                qty = min(bv, can_sell)
                orders.append(Order(product, bp, -qty))
                sell_vol += qty
            elif bp >= wall_mid and position > 0:
                # zero-edge clearing when long
                qty = min(bv, can_sell, position)
                if qty > 0:
                    orders.append(Order(product, bp, -qty))
                    sell_vol += qty
            else:
                break

        # ================================================================
        # 3. MAKING — Frankfurt-style: deep base, selective overbid
        # ================================================================
        bid_price = int(bid_wall + 1)
        ask_price = int(ask_wall - 1)

        # OVERBIDDING — raise our bid only if an inner bid with real volume
        # warrants it, and overbid stays under wall_mid.
        for bp in sorted(buys.keys(), reverse=True):
            bv = buys[bp]
            overbid = bp + 1
            if bv > 1 and overbid < wall_mid:
                bid_price = max(bid_price, overbid)
                break
            elif bp < wall_mid:
                bid_price = max(bid_price, bp)  # join their price
                break

        # UNDERBIDDING — mirror on ask side
        for sp in sorted(sells.keys()):
            sv = abs(sells[sp])
            underbid = sp - 1
            if sv > 1 and underbid > wall_mid:
                ask_price = min(ask_price, underbid)
                break
            elif sp > wall_mid:
                ask_price = min(ask_price, sp)
                break

        # Safety caps
        bid_price = min(bid_price, int(wall_mid) - 1)
        ask_price = max(ask_price, int(wall_mid) + 1)

        rem_buy = LIMIT - position - buy_vol
        if rem_buy > 0:
            orders.append(Order(product, bid_price, rem_buy))
        rem_sell = LIMIT + position - sell_vol
        if rem_sell > 0:
            orders.append(Order(product, ask_price, -rem_sell))

        return orders
