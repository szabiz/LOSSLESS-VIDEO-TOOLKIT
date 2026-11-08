# Deinterlace – QTGMC (havsfunc) – SABLON
# Csak az értékeket módosítsd (a # megjegyzésekben a lehetséges értékek vannak). A többi sor maradhat.
import vapoursynth as vs
import havsfunc as haf          # a havsfunc.py legyen a plugin-mappában (vagy a Python-útvonalon)

core = vs.core
src = globals().get("src", "")  # a forrásfájl: a program adja át (vspipe -a src=...)
if not src:
    raise vs.Error("Hiányzik a forrásfájl (src).")

if hasattr(core, "lsmas"):
    clip = core.lsmas.LWLibavSource(src)
elif hasattr(core, "ffms2"):
    clip = core.ffms2.Source(src)
else:
    raise vs.Error("Nincs forrás-betöltő plugin (lsmas vagy ffms2).")

clip = haf.QTGMC(
    clip,
    # Preset: Placebo | Very Slow | Slower | Slow | Medium | Fast | Faster | Very Fast | Super Fast | Ultra Fast | Draft
    #   alapértelmezett: Slower. Gyorsabb = gyengébb minőség, de gyorsabb feldolgozás.
    Preset="Medium",
    # TFF: True = felső mező elöl, False = alsó mező elöl. Ha rossz, a mozgó részek remegnek.
    TFF=True,
    # FPSDivisor: 2 = azonos képkockaszám (a mezőpárból 1 kép), 1 = dupla képkockaszám.
    FPSDivisor=2,
    # Sharpness: utóélesítés. Alapértelmezés 1.0 (SourceMatch mellett 0.2). 0.0 = nincs élesítés.
    Sharpness=1.0,
)

clip.set_output()
