"""Second independent reference for ethanol/water VLE: CalebBell `thermo` (MIT), NRTL with ChemSep parameters, and Peng-Robinson without BIPs.
Run in a venv with `thermo` (checked: thermo 0.6.1, chemicals 1.5.2). Saturation flashes (VF=0) failed in this Python (3.15), so the bubble
point is found by bisection on T-P flashes, the same way as for DWSIM."""
import warnings; warnings.filterwarnings("ignore")
from thermo import ChemicalConstantsPackage, PropertyCorrelationsPackage, FlashVL, GibbsExcessLiquid, IdealGas, CEOSGas, CEOSLiquid, PRMIX
from thermo.nrtl import NRTL
from thermo.interaction_parameters import IPDB
import thermo
print("thermo", thermo.__version__)
IDs = ["ethanol", "water"]
constants, correlations = ChemicalConstantsPackage.from_IDs(IDs)
def make(model):
    if model == "NRTL":
        ip = IPDB.get_ip_asymmetric_matrix("ChemSep NRTL", constants.CASs, "bij")
        alpha = IPDB.get_ip_asymmetric_matrix("ChemSep NRTL", constants.CASs, "alphaij")
        GE = lambda T, xs: NRTL(T=T, xs=xs, tau_bs=ip, alpha_cs=alpha)
        liquid = GibbsExcessLiquid(VaporPressures=correlations.VaporPressures, HeatCapacityGases=correlations.HeatCapacityGases,
                                   VolumeLiquids=correlations.VolumeLiquids, GibbsExcessModel=NRTL(T=350.0, xs=[.5,.5], tau_bs=ip, alpha_cs=alpha),
                                   equilibrium_basis="Poynting", caloric_basis="Poynting", T=350.0, P=101325.0, zs=[.5,.5])
        return FlashVL(constants, correlations, liquid=liquid, gas=IdealGas(HeatCapacityGases=correlations.HeatCapacityGases))
    if model == "PR":
        eos_kwargs = dict(Pcs=constants.Pcs, Tcs=constants.Tcs, omegas=constants.omegas)
        liquid = CEOSLiquid(PRMIX, HeatCapacityGases=correlations.HeatCapacityGases, eos_kwargs=eos_kwargs)
        gas = CEOSGas(PRMIX, HeatCapacityGases=correlations.HeatCapacityGases, eos_kwargs=eos_kwargs)
        return FlashVL(constants, correlations, liquid=liquid, gas=gas)

def bubble(fl, x, P=101325.0, lo=330.0, hi=380.0):
    for _ in range(50):
        mid = (lo + hi) / 2
        r = fl.flash(T=mid, P=P, zs=[x, 1 - x])
        two = (r.gas is not None)
        lo, hi = (mid, hi) if not two else (lo, mid)
        if hi - lo < 0.005: break
    r = fl.flash(T=hi + 0.01, P=P, zs=[x, 1 - x])
    return (lo + hi) / 2, (r.gas.zs[0] if r.gas is not None else None)
if __name__ == "__main__":
    for model in ("NRTL", "PR"):
        fl = make(model)
        for x in (1e-6 if False else 0.0001, 0.683, 0.894, 0.96, 0.9999):
            try: T, y = bubble(fl, x); print(model, x, "bubble T %.2f C" % (T - 273.15), "y_ethanol", None if y is None else round(y, 3))
            except Exception as e: print(model, x, "FAIL", repr(e)[:150])
