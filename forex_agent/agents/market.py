"""An independent gate for executable market conditions, without placing orders."""

from datetime import timedelta

from .contracts import SpecialistAgent
from ..models import SECONDS


class MarketConditionsAgent(SpecialistAgent):
    agent_id = "market_conditions"
    role = "Periksa spread, volatilitas, status pasar, dan jarak quote dari candle pemicu."
    depends_on = ("data_validation", "technical")
    payload_keys = ("spread",)

    def assess(self, context, technical):
        frame = technical[context.timeframe]
        spread, volatility = context.ask - context.bid, frame["atr14"]
        blocks = []
        if context.now >= context.frames[context.timeframe][-1].time + timedelta(seconds=SECONDS[context.timeframe]):
            blocks.append("Candle pemicu sudah kedaluwarsa; tunggu snapshot dengan candle terbaru.")
        if context.snapshot["quote"].get("tradeable") is not True:
            blocks.append("Pasar/instrumen sedang tidak dapat diperdagangkan.")
        if volatility <= 0 or spread > volatility * context.policy.max_spread_atr_fraction:
            blocks.append("Spread terlalu lebar relatif terhadap ATR atau ATR tidak valid.")
        if volatility > frame["atr_reference"] * 2.5:
            blocks.append("Lonjakan volatilitas ekstrem; tunggu kondisi stabil.")
        if abs((context.bid + context.ask) / 2 - frame["close"]) > volatility * 0.5:
            blocks.append("Harga berjalan telah menjauh dari candle analisis; tunggu candle baru.")
        return self.assessment("VETO" if blocks else "APPROVE", reasons=blocks,
                               payload={"spread": spread},
                               evidence={"spread": spread, "atr14": volatility,
                                         "tradeable": context.snapshot["quote"].get("tradeable") is True})
