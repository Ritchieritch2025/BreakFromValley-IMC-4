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
		worst_bid = bids[0]
		worst_ask = asks[-1]
		best_bid = bids[-1]
		best_ask = asks[0]
		mid = (best_bid + best_ask) / 2

		all_prices = list(order_depth.buy_orders.items()) + list(order_depth.sell_orders.items())
		total_volume = sum(abs(volume) for _, volume in all_prices)
		if total_volume > 0:
			vpa_level = sum(price * abs(volume) for price, volume in all_prices) / total_volume
		else:
			vpa_level = (worst_bid + worst_ask) / 2

		prev_vpa = trader_data.get("tomatoes_prev_vpa")
		prev_mid = trader_data.get("tomatoes_prev_mid")
		vpa_move = 0.0 if prev_vpa is None else vpa_level - prev_vpa
		price_move = 0.0 if prev_mid is None else mid - prev_mid
		deviation = mid - vpa_level

		trader_data["tomatoes_prev_vpa"] = vpa_level
		trader_data["tomatoes_prev_mid"] = mid

		buy_volume = 0
		sell_volume = 0
		fair_int = int(round(vpa_level))
		stable_vpa = abs(vpa_move) <= 0.5
		same_direction = price_move * vpa_move > 0
		price_up = price_move > 0
		price_down = price_move < 0

		# Step 1: use VPA as a fair-value anchor.
		# If price is stretched away from a stable VPA, fade the move.
		# If VPA is moving with price, join the move instead.
		if stable_vpa and abs(deviation) >= 1:
			if deviation > 0 and price_up:
				for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
					if bid_price <= fair_int:
						break
					bid_qty = order_depth.buy_orders[bid_price]
					can_sell = limit + position - sell_volume
					if can_sell <= 0:
						break
					qty = min(bid_qty, can_sell)
					if qty > 0:
						orders.append(Order(product, bid_price, -qty))
						sell_volume += qty
				for ask_price in sorted(order_depth.sell_orders.keys()):
					if ask_price >= fair_int:
						break
					ask_qty = abs(order_depth.sell_orders[ask_price])
					can_buy = limit - position - buy_volume
					if can_buy <= 0:
						break
					qty = min(ask_qty, can_buy)
					if qty > 0:
						orders.append(Order(product, ask_price, qty))
						buy_volume += qty

			elif deviation < 0 and price_down:
				for ask_price in sorted(order_depth.sell_orders.keys()):
					if ask_price >= fair_int:
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
					if bid_price <= fair_int:
						break
					bid_qty = order_depth.buy_orders[bid_price]
					can_sell = limit + position - sell_volume
					if can_sell <= 0:
						break
					qty = min(bid_qty, can_sell)
					if qty > 0:
						orders.append(Order(product, bid_price, -qty))
						sell_volume += qty
		elif same_direction and abs(deviation) >= 1:
			if price_up and vpa_move > 0:
				for ask_price in sorted(order_depth.sell_orders.keys()):
					if ask_price > fair_int + 1:
						break
					ask_qty = abs(order_depth.sell_orders[ask_price])
					can_buy = limit - position - buy_volume
					if can_buy <= 0:
						break
					qty = min(ask_qty, can_buy)
					if qty > 0:
						orders.append(Order(product, ask_price, qty))
						buy_volume += qty

			elif price_down and vpa_move < 0:
				for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
					if bid_price < fair_int - 1:
						break
					bid_qty = order_depth.buy_orders[bid_price]
					can_sell = limit + position - sell_volume
					if can_sell <= 0:
						break
					qty = min(bid_qty, can_sell)
					if qty > 0:
						orders.append(Order(product, bid_price, -qty))
						sell_volume += qty

		# If VPA is stable but price is not stretched enough to take aggressively,
		# still use resting liquidity around the VPA as a small inventory reducer.
		if not orders or abs(deviation) < 1:
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

		# Step 2: quote passively around the VPA level.
		# The quote skew respects inventory and nudges in the direction of the
		# current VPA regime.
		buy_price = min(fair_int - 1, best_bid + 1)
		sell_price = max(fair_int + 1, best_ask - 1)

		inventory_ratio = position / limit if limit else 0
		skew = int(round(inventory_ratio * 3))
		if same_direction and vpa_move > 0:
			skew -= 1
		elif same_direction and vpa_move < 0:
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
