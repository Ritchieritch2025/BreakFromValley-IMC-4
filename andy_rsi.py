import json

from datamodel import Order, OrderDepth, TradingState

EMERALD_FAIR_VALUE = 10000
EMERALD_POSITION_LIMIT = 80
TOMATOES_POSITION_LIMIT = 80


class Trader:
	def __init__(self):
		self.position_limits = {
			"EMERALDS": EMERALD_POSITION_LIMIT,
			"TOMATOES": TOMATOES_POSITION_LIMIT,
		}

	def run(self, state: TradingState):
		result = {}
		trader_data = {}

		if state.traderData:
			try:
				trader_data = json.loads(state.traderData)
			except (json.JSONDecodeError, TypeError):
				trader_data = {}

		for product, order_depth in state.order_depths.items():
			position = state.position.get(product, 0)
			limit = self.position_limits.get(product, 50)

			if product == "EMERALDS":
				orders = self.trade_emeralds(product, order_depth, position, limit)
			elif product == "TOMATOES":
				orders, trader_data = self.trade_tomatoes(product, order_depth, position, limit, trader_data)
			else:
				orders = []

			result[product] = orders

		return result, 0, json.dumps(trader_data)

	def trade_emeralds(self, product, order_depth: OrderDepth, position: int, limit: int):
		orders = []
		buy_volume = 0
		sell_volume = 0

		if not order_depth.buy_orders and not order_depth.sell_orders:
			return orders

		best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else EMERALD_FAIR_VALUE - 8
		best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else EMERALD_FAIR_VALUE + 8

		total_buy_volume = sum(order_depth.buy_orders.values())
		total_sell_volume = sum(abs(v) for v in order_depth.sell_orders.values())
		total_volume = total_buy_volume + total_sell_volume

		volume_pressure = 0.0
		if total_volume > 0:
			volume_pressure = (total_buy_volume - total_sell_volume) / total_volume

		volume_skew = int(round(volume_pressure * 2))
		fair_value = EMERALD_FAIR_VALUE + volume_skew

		# Step 1: take clearly favorable liquidity around fair value.
		for ask_price in sorted(order_depth.sell_orders.keys()):
			if ask_price >= fair_value:
				break

			ask_qty = abs(order_depth.sell_orders[ask_price])
			can_buy = limit - position - buy_volume
			if can_buy <= 0:
				break

			qty = min(ask_qty, can_buy)
			if qty > 0:
				orders.append(Order(product, ask_price, qty))
				buy_volume += qty

		for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
			if bid_price <= fair_value:
				break

			bid_qty = order_depth.buy_orders[bid_price]
			can_sell = limit + position - sell_volume
			if can_sell <= 0:
				break

			qty = min(bid_qty, can_sell)
			if qty > 0:
				orders.append(Order(product, bid_price, -qty))
				sell_volume += qty

		# Step 2: flatten at fair value if the book is resting there.
		fair_bid_volume = order_depth.buy_orders.get(fair_value, 0)
		if position > 0 and fair_bid_volume > 0:
			qty = min(fair_bid_volume, position, limit + position - sell_volume)
			if qty > 0:
				orders.append(Order(product, fair_value, -qty))
				sell_volume += qty

		fair_ask_volume = abs(order_depth.sell_orders.get(fair_value, 0))
		if position < 0 and fair_ask_volume > 0:
			qty = min(fair_ask_volume, -position, limit - position - buy_volume)
			if qty > 0:
				orders.append(Order(product, fair_value, qty))
				buy_volume += qty

		# Step 3: quote passively around fair value, skewed by inventory and volume imbalance.
		buy_price = min(fair_value - 1, best_bid + 1)
		sell_price = max(fair_value + 1, best_ask - 1)

		inventory_ratio = position / limit if limit else 0
		inventory_skew = int(round(inventory_ratio * 3))

		buy_price = min(fair_value - 1, buy_price - inventory_skew + volume_skew)
		sell_price = max(fair_value + 1, sell_price - inventory_skew + volume_skew)

		remaining_buy = limit - position - buy_volume
		if remaining_buy > 0:
			orders.append(Order(product, buy_price, remaining_buy))

		remaining_sell = limit + position - sell_volume
		if remaining_sell > 0:
			orders.append(Order(product, sell_price, -remaining_sell))

		return orders

	def trade_tomatoes(self, product, order_depth: OrderDepth, position: int, limit: int, trader_data):
		orders = []

		if not order_depth.buy_orders or not order_depth.sell_orders:
			return orders, trader_data

		bids = sorted(order_depth.buy_orders.keys())
		asks = sorted(order_depth.sell_orders.keys())
		best_bid = bids[-1]
		best_ask = asks[0]
		mid = (best_bid + best_ask) / 2

		# RSI calculation: 14-period RSI using Wilder's method
		RSI_PERIOD = 14
		RSI_OVERSOLD = 30
		RSI_OVERBOUGHT = 70

		if "tomatoes_prices" not in trader_data:
			trader_data["tomatoes_prices"] = []
		if "tomatoes_avg_gain" not in trader_data:
			trader_data["tomatoes_avg_gain"] = 0.0
		if "tomatoes_avg_loss" not in trader_data:
			trader_data["tomatoes_avg_loss"] = 0.0

		prices = trader_data["tomatoes_prices"]
		prices.append(mid)
		if len(prices) > RSI_PERIOD + 1:
			prices.pop(0)

		rsi = 50.0
		avg_gain = trader_data["tomatoes_avg_gain"]
		avg_loss = trader_data["tomatoes_avg_loss"]

		if len(prices) >= 2:
			change = prices[-1] - prices[-2]
			gain = change if change > 0 else 0.0
			loss = -change if change < 0 else 0.0

			if len(prices) <= RSI_PERIOD:
				avg_gain = (avg_gain * (len(prices) - 2) + gain) / (len(prices) - 1) if len(prices) > 1 else gain
				avg_loss = (avg_loss * (len(prices) - 2) + loss) / (len(prices) - 1) if len(prices) > 1 else loss
			else:
				avg_gain = (avg_gain * (RSI_PERIOD - 1) + gain) / RSI_PERIOD
				avg_loss = (avg_loss * (RSI_PERIOD - 1) + loss) / RSI_PERIOD

			if avg_loss == 0:
				rsi = 100.0 if avg_gain > 0 else 50.0
			else:
				rs = avg_gain / avg_loss
				rsi = 100.0 - (100.0 / (1.0 + rs))

		trader_data["tomatoes_avg_gain"] = avg_gain
		trader_data["tomatoes_avg_loss"] = avg_loss
		trader_data["tomatoes_rsi"] = rsi

		# Fair value: use mid as anchor
		fair_int = int(round(mid))
		buy_volume = 0
		sell_volume = 0

		# RSI-based trading rules:
		# 1. RSI < 30: oversold, buy (fade downtrend)
		# 2. RSI > 70: overbought, sell (fade uptrend)
		# 3. 30 <= RSI <= 70: neutral, make market
		# 4. Guard against RSI staying in extremes (lagging warning)

		rsi_extreme_frames = trader_data.get("tomatoes_rsi_extreme_frames", 0)
		if rsi < RSI_OVERSOLD or rsi > RSI_OVERBOUGHT:
			rsi_extreme_frames += 1
		else:
			rsi_extreme_frames = 0
		trader_data["tomatoes_rsi_extreme_frames"] = rsi_extreme_frames

		# Reduce trade size if RSI stays extreme for >10 ticks (lagging warning)
		aggressiveness = 1.0 if rsi_extreme_frames <= 10 else 0.5

		if rsi < RSI_OVERSOLD and rsi_extreme_frames <= 15:
			# Oversold: buy ask aggressively
			for ask_price in sorted(order_depth.sell_orders.keys()):
				if ask_price > fair_int + 2:
					break
				ask_qty = abs(order_depth.sell_orders[ask_price])
				can_buy = int((limit - position - buy_volume) * aggressiveness)
				if can_buy <= 0:
					break
				qty = min(ask_qty, can_buy)
				if qty > 0:
					orders.append(Order(product, ask_price, qty))
					buy_volume += qty

		elif rsi > RSI_OVERBOUGHT and rsi_extreme_frames <= 15:
			# Overbought: sell bid aggressively
			for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
				if bid_price < fair_int - 2:
					break
				bid_qty = order_depth.buy_orders[bid_price]
				can_sell = int((limit + position - sell_volume) * aggressiveness)
				if can_sell <= 0:
					break
				qty = min(bid_qty, can_sell)
				if qty > 0:
					orders.append(Order(product, bid_price, -qty))
					sell_volume += qty

		# Step 2: flatten inventory around mid + RSI bias.
		if position > 0 and order_depth.buy_orders.get(fair_int, 0) > 0:
			qty = min(order_depth.buy_orders[fair_int], position, limit + position - sell_volume)
			if qty > 0:
				orders.append(Order(product, fair_int, -qty))
				sell_volume += qty
		elif position < 0 and abs(order_depth.sell_orders.get(fair_int, 0)) > 0:
			qty = min(abs(order_depth.sell_orders[fair_int]), -position, limit - position - buy_volume)
			if qty > 0:
				orders.append(Order(product, fair_int, qty))
				buy_volume += qty

		# Step 3: quote passively around mid with RSI-aware skew.
		buy_price = best_bid + 1
		sell_price = best_ask - 1

		buy_price = min(buy_price, fair_int - 1)
		sell_price = max(sell_price, fair_int + 1)

		inventory_ratio = position / limit if limit else 0.0
		skew = int(round(inventory_ratio * 3))

		if rsi < 40:
			skew -= 1
		elif rsi > 60:
			skew += 1

		buy_price = min(fair_int - 1, buy_price - skew)
		sell_price = max(fair_int + 1, sell_price - skew)

		remaining_buy = limit - position - buy_volume
		if remaining_buy > 0:
			orders.append(Order(product, buy_price, remaining_buy))

		remaining_sell = limit + position - sell_volume
		if remaining_sell > 0:
			orders.append(Order(product, sell_price, -remaining_sell))

		return orders, trader_data
