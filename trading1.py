from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import json
import math


class Trader:
    POSITION_LIMITS = {
        "EMERALDS": 50,
        "TOMATOES": 50,
    }

    def _load_state(self, td: str) -> dict:
        if td and td.strip():
            try:
                return json.loads(td)
            except Exception:
                pass
        return {}

    def _save_state(self, s: dict) -> str:
        return json.dumps(s)

    # ============================================================
    #  EMERALDS: 严格固定价值 10000
    #  改进：优化吃单(Taker)逻辑，确保每笔主动交易都有正向Edge。
    #  改进：更平滑的库存倾斜(Inventory Skew)机制，避免单边仓位过重。
    # ============================================================
    def trade_emeralds(self, state: TradingState, persistent: dict) -> List[Order]:
        product = "EMERALDS"
        if product not in state.order_depths:
            return []

        od = state.order_depths[product]
        position = state.position.get(product, 0)
        limit = self.POSITION_LIMITS[product]
        fair = 10000

        orders: List[Order] = []
        buy_avail = limit - position
        sell_avail = limit + position

        # ---- 1. Taker 策略 (主动吃单，只吃有利润的单) ----
        if od.sell_orders:
            for price in sorted(od.sell_orders.keys()):
                # 只主动买入价格严格小于 10000 的订单，确保利润
                if price < fair and buy_avail > 0:
                    vol = min(abs(od.sell_orders[price]), buy_avail)
                    if vol > 0:
                        orders.append(Order(product, price, vol))
                        buy_avail -= vol

        if od.buy_orders:
            for price in sorted(od.buy_orders.keys(), reverse=True):
                # 只主动卖出价格严格大于 10000 的订单
                if price > fair and sell_avail > 0:
                    vol = min(od.buy_orders[price], sell_avail)
                    if vol > 0:
                        orders.append(Order(product, price, -vol))
                        sell_avail -= vol

        # ---- 2. Maker 策略 (被动做市) ----
        est_pos = position + sum(o.quantity for o in orders)
        buy_avail = limit - est_pos
        sell_avail = limit + est_pos

        # 库存倾斜 (Inventory Skew): 仓位越大，报价越保守
        # 仓位为正（多头）时，降低买价和卖价，促使卖出
        skew = 0
        if abs(est_pos) > 10:
            skew = -int(est_pos / 15)  # 仓位达到 30 时，skew 为 -2

        # 基础报价定在 9997 和 10003，结合 skew 进行偏移
        bid_price = 9997 + skew
        ask_price = 10003 + skew

        # 安全检查：确保做市报价不会越过公允价值产生亏损
        bid_price = min(bid_price, fair - 1)
        ask_price = max(ask_price, fair + 1)

        if buy_avail > 0:
            orders.append(Order(product, bid_price, buy_avail))
        if sell_avail > 0:
            orders.append(Order(product, ask_price, -sell_avail))

        return orders

    # ============================================================
    #  TOMATOES: 动态公允价值 (Microprice + EMA)
    #  改进：引入 Order Book Imbalance 计算微观价格，对趋势预判极度敏锐。
    #  改进：软性仓位限制与动态价差，防范单边趋势造成的巨大浮亏。
    # ============================================================
    def trade_tomatoes(self, state: TradingState, persistent: dict) -> List[Order]:
        product = "TOMATOES"
        if product not in state.order_depths:
            return []

        od = state.order_depths[product]
        position = state.position.get(product, 0)
        limit = self.POSITION_LIMITS[product]

        best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None

        if best_bid is None or best_ask is None:
            return []

        # 获取最优买卖价的挂单量
        bid_vol = od.buy_orders[best_bid]
        ask_vol = abs(od.sell_orders[best_ask])

        # ---- 1. 计算微观价格 (Microprice) ----
        # 相比普通的 (bid+ask)/2，Microprice 考虑了买卖盘的压力差
        # 如果买单量巨大，微观价格会更贴近 ask_price，预示价格即将上涨
        total_vol = bid_vol + ask_vol
        microprice = (best_bid * ask_vol + best_ask * bid_vol) / total_vol

        # ---- 2. 结合 EMA 平滑趋势 ----
        ema_key = "tom_ema"
        prev_ema = persistent.get(ema_key)
        alpha = 0.3  # 反应速度参数，适中以过滤噪音

        if prev_ema is not None:
            ema = alpha * microprice + (1 - alpha) * prev_ema
        else:
            ema = microprice
        persistent[ema_key] = ema

        # 最终公允价值：Microprice 赋予更高权重，EMA 作为底座
        fair = 0.7 * microprice + 0.3 * ema

        orders: List[Order] = []
        buy_avail = limit - position
        sell_avail = limit + position

        # ---- 3. Taker 策略：只吃具有明显 Edge 的单子 ----
        # 要求至少有 1.5 ticks 的利润空间
        if od.sell_orders:
            for price in sorted(od.sell_orders.keys()):
                if price < fair - 1.5 and buy_avail > 0:
                    vol = min(abs(od.sell_orders[price]), buy_avail)
                    if vol > 0:
                        orders.append(Order(product, price, vol))
                        buy_avail -= vol

        if od.buy_orders:
            for price in sorted(od.buy_orders.keys(), reverse=True):
                if price > fair + 1.5 and sell_avail > 0:
                    vol = min(od.buy_orders[price], sell_avail)
                    if vol > 0:
                        orders.append(Order(product, price, -vol))
                        sell_avail -= vol

        est_pos = position + sum(o.quantity for o in orders)
        buy_avail = limit - est_pos
        sell_avail = limit + est_pos

        # ---- 4. 极端库存控制 (Aggressive Flattening) ----
        # 当仓位面临趋势风险时，主动平仓
        DANGER_LIMIT = 30
        if est_pos > DANGER_LIMIT and sell_avail > 0:
            # 仓位过重且处于多头，降价主动砸盘到 best_bid 止损/止盈
            flatten_qty = min(est_pos - 15, sell_avail)
            orders.append(Order(product, best_bid, -flatten_qty))
            sell_avail -= flatten_qty
            est_pos -= flatten_qty

        elif est_pos < -DANGER_LIMIT and buy_avail > 0:
            # 仓位过重且处于空头，提价主动买入到 best_ask
            flatten_qty = min(abs(est_pos) - 15, buy_avail)
            orders.append(Order(product, best_ask, flatten_qty))
            buy_avail -= flatten_qty
            est_pos += flatten_qty

        # ---- 5. Maker 策略：动态价差做市 ----
        inv_skew = -est_pos * 0.1  # 库存偏移系数

        # 基础半价差为 4，仓位越高，价差拉得越宽，防止被单边打穿
        half_spread = 4.0
        if abs(est_pos) > 15:
            half_spread += 1.0
        if abs(est_pos) > 25:
            half_spread += 1.5

        bid_price = int(math.floor(fair - half_spread + inv_skew))
        ask_price = int(math.ceil(fair + half_spread + inv_skew))

        # 防止自成交 (Self-crossing)
        if bid_price >= ask_price:
            bid_price = ask_price - 1

        # 挂单规模控制：仓位大时，劣势方向的挂单量减少
        base_size = limit // 2
        bid_size = min(buy_avail, base_size)
        ask_size = min(sell_avail, base_size)

        if est_pos > 10:
            bid_size = max(2, bid_size - int(est_pos / 2))
        elif est_pos < -10:
            ask_size = max(2, ask_size - int(abs(est_pos) / 2))

        if bid_size > 0:
            orders.append(Order(product, bid_price, bid_size))
        if ask_size > 0:
            orders.append(Order(product, ask_price, -ask_size))

        return orders

    # ============================================================
    #  主入口
    # ============================================================
    def run(self, state: TradingState):
        persistent = self._load_state(state.traderData)
        result: Dict[str, List[Order]] = {}

        result["EMERALDS"] = self.trade_emeralds(state, persistent)
        result["TOMATOES"] = self.trade_tomatoes(state, persistent)

        conversions = 0
        trader_data = self._save_state(persistent)
        return result, conversions, trader_data