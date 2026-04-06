import json

from datamodel import Order, TradingState


class Trader:
    def __init__(self):
        self.position_limits = {
            "EMERALDS": 80,
            "TOMATOES": 80,
        }

    def run(self, state: TradingState):
        result = {}

        # Restore persisted state (EMA values, etc.)
        trader_data = {}
        if state.traderData:
            try:
                trader_data = json.loads(state.traderData)
            except (json.JSONDecodeError, TypeError):
                trader_data = {}

        for product in state.order_depths:
            order_depth = state.order_depths[product]
            position = state.position.get(product, 0)
            limit = self.position_limits.get(product, 50)

            if product == "EMERALDS":
                orders = self.trade_emeralds(product, order_depth, position, limit)
            elif product == "TOMATOES":
                orders, trader_data = self.trade_tomatoes(
                    product, order_depth, position, limit, trader_data
                )
            else:
                orders = []

            result[product] = orders

        return result, 0, json.dumps(trader_data)

    def trade_emeralds(self, product, order_depth, position, limit):
        """
        EMERALDS v4: Ritchie's design
        1. Read order book and position
        2. Take obviously favorable trades (ask < 10000 → buy, bid > 10000 → sell)
        3. Flatten at fair value (buy/sell at 10000 to reduce position)
        4. Passive maker quotes with undercut + continuous skew
        """
        FAIR = 10000
        orders = []
        buy_volume = 0
        sell_volume = 0

        best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else FAIR - 8
        best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else FAIR + 8

        # === Step 1: Take favorable trades ===
        # Buy anything asked below fair value
        if order_depth.sell_orders:
            for ask_price in sorted(order_depth.sell_orders.keys()):
                if ask_price >= FAIR:
                    break
                ask_qty = abs(order_depth.sell_orders[ask_price])
                can_buy = limit - position - buy_volume
                if can_buy <= 0:
                    break
                qty = min(ask_qty, can_buy)
                orders.append(Order(product, ask_price, qty))
                buy_volume += qty

        # Sell to anyone bidding above fair value
        if order_depth.buy_orders:
            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                if bid_price <= FAIR:
                    break
                bid_qty = order_depth.buy_orders[bid_price]
                can_sell = limit + position - sell_volume
                if can_sell <= 0:
                    break
                qty = min(bid_qty, can_sell)
                orders.append(Order(product, bid_price, -qty))
                sell_volume += qty

        # === Step 2: Flatten at fair value ===
        # If someone is quoting AT 10000, use it to reduce position
        if position > 0 and order_depth.buy_orders.get(FAIR, 0) > 0:
            bid_qty = order_depth.buy_orders[FAIR]
            can_sell = limit + position - sell_volume
            qty = min(bid_qty, can_sell, position)  # only flatten, don't flip
            if qty > 0:
                orders.append(Order(product, FAIR, -qty))
                sell_volume += qty
        elif position < 0 and order_depth.sell_orders.get(FAIR, 0) != 0:
            ask_qty = abs(order_depth.sell_orders[FAIR])
            can_buy = limit - position - buy_volume
            qty = min(ask_qty, can_buy, -position)  # only flatten, don't flip
            if qty > 0:
                orders.append(Order(product, FAIR, qty))
                buy_volume += qty

        # === Step 3: Passive maker quotes ===
        # Undercut: penny the best bid/ask, but never cross fair value
        buy_price = min(FAIR - 1, best_bid + 1)
        sell_price = max(FAIR + 1, best_ask - 1)

        # Continuous skew based on inventory
        inventory_ratio = position / limit  # range [-1, 1]
        skew = int(inventory_ratio * 3)     # range [-3, 3]

        buy_price = buy_price - skew
        sell_price = sell_price - skew

        # Safety: never cross fair value
        buy_price = min(buy_price, FAIR - 1)
        sell_price = max(sell_price, FAIR + 1)

        remaining_buy = limit - position - buy_volume
        if remaining_buy > 0:
            orders.append(Order(product, buy_price, remaining_buy))

        remaining_sell = limit + position - sell_volume
        if remaining_sell > 0:
            orders.append(Order(product, sell_price, -remaining_sell))

        return orders

    def trade_tomatoes(self, product, order_depth, position, limit, trader_data):
        """
        TOMATOES v3: Mean-Reversion with EMA Fair Value

        Key insight: lag-1 autocorrelation = -0.44 → strong mean reversion
        When price spikes above EMA → sell (expect revert)
        When price dips below EMA → buy (expect revert)

        EMA smooths noise, lags behind price → natural mean-reversion signal
        """
        orders = []

        if not order_depth.buy_orders or not order_depth.sell_orders:
            return orders, trader_data

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid = (best_bid + best_ask) / 2

        # === EMA fair value ===
        EMA_ALPHA = 0.15  # Slower EMA = more smoothing = bigger mean-reversion signals
        ema_key = "tomatoes_ema"

        if ema_key in trader_data:
            ema = trader_data[ema_key]
            ema = EMA_ALPHA * mid + (1 - EMA_ALPHA) * ema
        else:
            ema = mid  # Initialize on first tick

        trader_data[ema_key] = ema
        fair_value = ema

        buy_volume = 0
        sell_volume = 0

        # === Taking: exploit mean-reversion when price deviates from EMA ===
        TAKE_LIMIT = 25  # stop taking if already holding 25+ in same direction

        # When asks are significantly below EMA → price dipped, buy (expect revert up)
        if position < TAKE_LIMIT:  # only take if not already too long
            for ask_price in sorted(order_depth.sell_orders.keys()):
                if ask_price >= fair_value - 2:
                    break
                ask_qty = abs(order_depth.sell_orders[ask_price])
                can_buy = min(limit - position - buy_volume, TAKE_LIMIT - position)
                if can_buy <= 0:
                    break
                qty = min(ask_qty, can_buy)
                orders.append(Order(product, ask_price, qty))
                buy_volume += qty

        # When bids are significantly above EMA → price spiked, sell (expect revert down)
        if position > -TAKE_LIMIT:  # only take if not already too short
            for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                if bid_price <= fair_value + 2:
                    break
                bid_qty = order_depth.buy_orders[bid_price]
                can_sell = min(limit + position - sell_volume, TAKE_LIMIT + position)
                if can_sell <= 0:
                    break
                qty = min(bid_qty, can_sell)
                orders.append(Order(product, bid_price, -qty))
                sell_volume += qty

        # === Making: quote around EMA with position skew ===
        buy_price = int(fair_value) - 3
        sell_price = int(fair_value) + 3

        # Position-based skew
        pos_ratio = position / limit
        if pos_ratio > 0.25:
            # Long: tighten sell (eager to reduce), widen buy (less eager to add)
            sell_price -= 1
            buy_price -= 1
            if pos_ratio > 0.5:
                sell_price -= 1
                buy_price -= 1
        elif pos_ratio < -0.25:
            # Short: tighten buy (eager to reduce), widen sell (less eager to add)
            buy_price += 1
            sell_price += 1
            if pos_ratio < -0.5:
                buy_price += 1
                sell_price += 1

        # Aggressive flattening when near limits
        if abs(position) > limit * 0.75:
            if position > 0:
                # Very long: market sell to flatten
                sell_price = best_bid  # Hit the bid
            else:
                # Very short: market buy to flatten
                buy_price = best_ask  # Lift the ask

        remaining_buy = limit - position - buy_volume
        if remaining_buy > 0:
            orders.append(Order(product, buy_price, remaining_buy))

        remaining_sell = limit + position - sell_volume
        if remaining_sell > 0:
            orders.append(Order(product, sell_price, -remaining_sell))

        return orders, trader_data
