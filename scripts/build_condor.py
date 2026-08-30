"""Build a real iron condor from live SPY data and show the exact order payload."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import date

from agent.client import AlpacaClient
from agent import options as O
from agent import spreads as S

TODAY = date(2026, 8, 30)
UND, EXPIRY = "SPY", date(2026, 9, 4)

c = AlpacaClient()
spot = c.latest_trade(UND)

chain = c.option_chain(UND, exp=EXPIRY.isoformat(),
                       strike_gte=spot * 0.92, strike_lte=spot * 1.08)
rejects = []
views = O.usable_contracts(chain, today=TODAY, collect_rejects=rejects)

iv = O.atm_iv(views, spot, EXPIRY)
dte = (EXPIRY - TODAY).days
em = O.expected_move(spot, iv, dte)

ladder_c = O.strike_ladder(views, "C", EXPIRY)
ladder_p = O.strike_ladder(views, "P", EXPIRY)
width = max(O.typical_width(ladder_c), 1.0) * 5      # 5 strikes wide

print(f"{UND} ${spot:.2f} | ATM IV {iv:.1%} | {dte} DTE | 1σ expected move ${em:.2f}")
print(f"usable contracts: {len(views)} (rejected {len(rejects)}) | wing width ${width:.0f}")

# short strikes ~1.25 sigma out, protective wings 5 strikes beyond
short_put  = O.by_strike(views, spot - 1.25 * em, "P", EXPIRY)
short_call = O.by_strike(views, spot + 1.25 * em, "C", EXPIRY)
long_put   = O.wing(views, short_put,  width)
long_call  = O.wing(views, short_call, width)

for name, v in [("long put", long_put), ("short put", short_put),
                ("short call", short_call), ("long call", long_call)]:
    print(f"  {name:11} {v.symbol}  K={v.strike:<7.1f} mid={v.mid:6.2f} "
          f"delta={v.delta:+.3f} theta={v.theta:+.3f} iv={v.iv:.1%}")

condor = S.iron_condor(long_put, short_put, short_call, long_call, qty=1)
print("\n" + condor.describe())
print(f"  credit received : ${abs(condor.net_price) * 100:.0f}")
print(f"  max loss        : ${condor.total_max_loss():.0f}")
print(f"  breakevens      : ${short_put.strike - abs(condor.net_price):.2f}"
      f"  <->  ${short_call.strike + abs(condor.net_price):.2f}")
print(f"  win zone width  : ${short_call.strike - short_put.strike:.0f} "
      f"({(short_call.strike - short_put.strike) / spot:.1%} of spot)")

body = condor.order()
errs = S.validate_mleg(body)
print("\nvalidator:", "✅ PASS" if not errs else f"❌ {errs}")
print("\norder payload:")
print(json.dumps(body, indent=2))
json.dump(body, open("/tmp/condor.json", "w"))
