#!/usr/bin/env python3
"""aldia: pone al día todos tus repositorios de escritura de una vez.

  aldia                 al empezar y al terminar la sesión: en cada repositorio
                        guarda los cambios (commit), trae lo de otros equipos
                        (pull) y sube lo tuyo (push), como guarda en todos a la vez
  aldia "mensaje"       lo mismo, con ese mensaje en los commits
  aldia --estado        solo mirar: qué tiene cambios, qué falta por subir
  aldia --instalar      añadir la orden aldia a PowerShell / bash / zsh

Repositorios que recorre, en este orden (los que no estén en este equipo se saltan):
  la configuración de Neovim, la de Pandoc (pandoc-config), ~/bibliografia,
  y cada repositorio dentro de ~/escritura (academic-writing, blog, los literarios...).
Para añadir otro, ponlo en EXTRA, abajo.

Si dos equipos cambiaron la misma parte del mismo archivo, aldia guarda tu
versión en un commit, no toca nada más y lo marca con ✗. Nada se pierde. Para
resolverlo, en esa carpeta:
  git pull                 git marca el choque con <<<<<<< ======= >>>>>>>
  (edita el archivo: deja el texto bueno y borra las marcas)
  git add -A
  git rebase --continue
  aldia                    y todo sigue como siempre

El blog es especial: subirlo es publicarlo. Antes de subir un sitio de Hugo,
aldia enseña qué entradas se publicarían o retirarían y pregunta.
"""

# ---- Ajustes ------------------------------------------------------------
EXTRA = []                 # otras carpetas, p. ej. ["~/docencia/apuntes"]
ESCRITURA = "~/escritura"  # cada repositorio de aquí dentro entra solo
# -------------------------------------------------------------------------

import datetime as dt
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

WINDOWS = os.name == "nt"
SCRIPT = Path(__file__).resolve()

_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
if WINDOWS and _COLOR:
    os.system("")  # activa los colores en la consola de Windows


def _c(code):
    return f"\033[{code}m" if _COLOR else ""


B, T, V, A, Rj, R = _c(1), _c(2), _c(32), _c(33), _c(31), _c(0)


# ---- Qué repositorios -------------------------------------------------------
def repositorios():
    home = Path.home()
    if WINDOWS:
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        fijos = [("Neovim", local / "nvim"), ("pandoc-config", roaming / "pandoc")]
    else:
        config = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
        datos = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))
        fijos = [("Neovim", config / "nvim"), ("pandoc-config", datos / "pandoc")]
        if not (datos / "pandoc").exists() and (home / ".pandoc").exists():
            fijos[1] = ("pandoc-config", home / ".pandoc")
    fijos.append(("bibliografia", home / "bibliografia"))

    vistos, lista = set(), []

    def poner(nombre, ruta):
        ruta = ruta.expanduser()
        clave = str(ruta.resolve()) if ruta.exists() else str(ruta)
        if clave not in vistos:
            vistos.add(clave)
            lista.append((nombre, ruta))

    for nombre, ruta in fijos:
        poner(nombre, ruta)
    esc = Path(ESCRITURA).expanduser()
    if (esc / ".git").exists():
        poner(esc.name, esc)
    if esc.is_dir():
        for sub in sorted(esc.iterdir(), key=lambda p: p.name.lower()):
            if sub.is_dir() and (sub / ".git").exists():
                poner(sub.name, sub)
    for extra in EXTRA:
        p = Path(extra).expanduser()
        poner(p.name, p)
    return lista


# ---- Git --------------------------------------------------------------------
def git(repo, *args, timeout=120):
    """Devuelve (ok, salida). Deja pasar las preguntas de contraseña de ssh."""
    try:
        r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "sin respuesta del servidor (¿hay conexión?)"
    except OSError as e:
        return False, str(e)


def n(cuantos, singular, plural):
    return f"{cuantos} {singular if cuantos == 1 else plural}"


def ultima_linea(texto):
    lineas = [l for l in texto.splitlines() if l.strip() and not l.startswith("hint:")]
    return lineas[-1].strip() if lineas else ""


def cambios(repo):
    ok, out = git(repo, "status", "--porcelain", "-uall", timeout=30)
    return [l for l in out.splitlines() if l.strip()] if ok else []


def contar(repo, rango):
    ok, out = git(repo, "rev-list", "--count", rango, timeout=30)
    return int(out) if ok and out.isdigit() else 0


def rebase_a_medias(repo):
    ok, gitdir = git(repo, "rev-parse", "--git-dir", timeout=30)
    if not ok:
        return False
    d = Path(gitdir) if Path(gitdir).is_absolute() else repo / gitdir
    return (d / "rebase-merge").exists() or (d / "rebase-apply").exists()


# ---- El blog ----------------------------------------------------------------
def es_hugo(repo):
    return any((repo / f).exists() for f in
               ("hugo.toml", "hugo.yaml", "hugo.json", "config.toml", "config.yaml"))


def es_borrador(archivo: Path):
    try:
        texto = archivo.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    m = re.match(r"^(---|\+\+\+)\s*\n(.*?)\n\1", texto, re.S)
    return bool(m and re.search(r"^\s*draft\s*[:=]\s*true\b", m.group(2), re.M | re.I))


def publicaria(repo, lineas_status):
    """Entradas que se publicarían o retirarían al subir el sitio."""
    nuevas, retiradas = [], []
    for l in lineas_status:
        estado, ruta = l[:2], l[3:].strip().strip('"')
        if " -> " in ruta:
            ruta = ruta.split(" -> ", 1)[1]
        if not (ruta.startswith("content/") and ruta.endswith(".md")):
            continue
        if "D" in estado:
            retiradas.append(ruta)
        elif not es_borrador(repo / ruta):
            nuevas.append(ruta)
    return nuevas, retiradas


def si_no(texto, defecto="s"):
    if not sys.stdin.isatty():
        return defecto == "s"
    op = "[S/n]" if defecto == "s" else "[s/N]"
    try:
        r = input(f"{texto} {op}: ").strip().lower() or defecto
    except EOFError:
        r = defecto
    return r in ("s", "si", "sí", "y", "yes")


# ---- Un repositorio ---------------------------------------------------------
def poner_al_dia(nombre, repo, mensaje, solo_mirar=False):
    etiqueta = f"{B}{nombre:<18}{R}"
    if not repo.exists():
        print(f"  {T}· {nombre:<18} no está en este equipo (buscado en {repo}){R}")
        return "ausente"
    if not (repo / ".git").exists():
        dentro = [d for d in repo.iterdir() if d.is_dir() and (d / ".git").exists()]
        if dentro:
            print(f"  {A}!{R} {etiqueta} el repositorio está un nivel más abajo, en {dentro[0]};"
                  f" debería estar en {repo}")
        else:
            print(f"  {A}!{R} {etiqueta} la carpeta {repo} existe, pero no es un clon de git")
        return "aviso"
    if rebase_a_medias(repo):
        print(f"  {Rj}✗{R} {etiqueta} tiene un pull a medias; resuélvelo antes (git status)")
        return "error"

    partes = []
    pendientes = cambios(repo)
    tiene_upstream, upstream = git(repo, "rev-parse", "--abbrev-ref", "@{u}", timeout=30)

    if solo_mirar:
        git(repo, "fetch", "-q", timeout=60)
        if pendientes:
            partes.append(f"{A}{n(len(pendientes), 'cambio sin guardar', 'cambios sin guardar')}{R}")
        if tiene_upstream:
            fuera, dentro = contar(repo, "@{u}..HEAD"), contar(repo, "HEAD..@{u}")
            if fuera:
                partes.append(f"{A}{n(fuera, 'commit sin subir', 'commits sin subir')}{R}")
            if dentro:
                partes.append(n(dentro, "commit por traer", "commits por traer"))
        else:
            partes.append(f"{A}sin rama remota{R}")
        print(f"  {'·' if partes else V + '✓' + R} {etiqueta} " + (" · ".join(partes) or "al día"))
        return "ok"

    # 1. Guardar lo local, como guarda
    subir_permitido = True
    if pendientes:
        if es_hugo(repo):
            nuevas, retiradas = publicaria(repo, pendientes)
            if nuevas or retiradas:
                print(f"  {A}!{R} {etiqueta} subir el blog es publicarlo:")
                for r_ in nuevas:
                    print(f"      se publicará   {r_}")
                for r_ in retiradas:
                    print(f"      se retirará    {r_}")
                print(f"      {T}(las entradas con draft: true suben a GitHub pero no se publican){R}")
                subir_permitido = si_no("      ¿Publicar ahora?", "n")
        if subir_permitido:
            git(repo, "add", "-A", timeout=60)
            ok, out = git(repo, "commit", "-q", "-m", mensaje, timeout=60)
            if ok:
                partes.append(n(len(pendientes), "cambio guardado", "cambios guardados"))
            else:
                partes.append(f"{A}no he podido guardar: {ultima_linea(out)}{R}")
        else:
            partes.append(f"{A}cambios sin subir, a petición tuya{R}")

    if not tiene_upstream:
        partes.append(f"{A}sin rama remota (haz una vez: git push -u origin main){R}")
        print(f"  {A}·{R} {etiqueta} " + " · ".join(partes))
        return "aviso"

    # 2. Traer lo de otros equipos
    antes_remoto = git(repo, "rev-parse", "@{u}", timeout=30)[1]
    ok, out = git(repo, "pull", "--rebase", "--autostash")
    if not ok:
        if rebase_a_medias(repo):
            git(repo, "rebase", "--abort", timeout=60)
            partes.append(f"{Rj}choca con lo que subió otro equipo; tu versión está a salvo "
                          f"en un commit. Cómo resolverlo: aldia --help{R}")
        else:
            partes.append(f"{Rj}no he podido traer: {ultima_linea(out)}{R}")
        print(f"  {Rj}✗{R} {etiqueta} " + " · ".join(partes))
        return "error"
    despues_remoto = git(repo, "rev-parse", "@{u}", timeout=30)[1]
    traidos = contar(repo, f"{antes_remoto}..{despues_remoto}") if antes_remoto != despues_remoto else 0
    if traidos:
        partes.append(n(traidos, "commit traído", "commits traídos"))
    if (repo / ".gitmodules").exists():
        git(repo, "submodule", "update", "--init", "--recursive", timeout=180)

    # 3. Subir lo propio
    por_subir = contar(repo, "@{u}..HEAD")
    if por_subir and subir_permitido:
        ok, out = git(repo, "push", "-q")
        if ok:
            partes.append(n(por_subir, "commit subido", "commits subidos") + (" (publicándose)" if es_hugo(repo) else ""))
        else:
            partes.append(f"{Rj}no he podido subir: {ultima_linea(out)}{R}")
            print(f"  {Rj}✗{R} {etiqueta} " + " · ".join(partes))
            return "error"
    elif por_subir:
        partes.append(f"{A}{n(por_subir, 'commit sin subir', 'commits sin subir')}{R}")

    print(f"  {V}✓{R} {etiqueta} " + (" · ".join(partes) or "al día"))
    return "ok"


# ---- Instalación ------------------------------------------------------------
MARCA_INI, MARCA_FIN = "# >>> aldia >>>", "# <<< aldia <<<"


def poner_bloque(archivo: Path, bloque: str):
    try:
        texto = archivo.read_text(encoding="utf-8") if archivo.exists() else ""
    except UnicodeDecodeError:
        print(f"  {archivo}: no está en UTF-8 y no lo toco. Pega a mano al final:")
        print("    " + bloque)
        return
    nuevo = f"{MARCA_INI}\n{bloque}\n{MARCA_FIN}"
    if MARCA_INI in texto and MARCA_FIN in texto:
        a, b = texto.index(MARCA_INI), texto.index(MARCA_FIN) + len(MARCA_FIN)
        texto, accion = texto[:a] + nuevo + texto[b:], "actualizado"
    else:
        texto = texto + ("\n" if texto and not texto.endswith("\n") else "") + "\n" + nuevo + "\n"
        accion = "añadido"
    archivo.parent.mkdir(parents=True, exist_ok=True)
    archivo.write_text(texto, encoding="utf-8")
    print(f"  {archivo}: {accion}.")


def instalar():
    py = Path(sys.executable)
    if WINDOWS and py.name.lower() == "pythonw.exe":
        py = py.with_name("python.exe")
    print(f"{B}Preparando aldia en este equipo{R}")
    if WINDOWS:
        import shutil
        bloque = f"function aldia {{ & '{py}' '{SCRIPT}' @args }}"
        perfiles = set()
        for exe in ("powershell.exe", "pwsh.exe"):
            if exe == "pwsh.exe" and not shutil.which(exe):
                continue
            r = subprocess.run([exe, "-NoProfile", "-Command", "$PROFILE"],
                               capture_output=True, text=True)
            if r.returncode == 0 and r.stdout.strip():
                perfiles.add(Path(r.stdout.strip()))
        for p in sorted(perfiles):
            poner_bloque(p, bloque)
    else:
        bloque = f"alias aldia='\"{py}\" \"{SCRIPT}\"'"
        rcs = [Path.home() / ".bashrc"]
        if (Path.home() / ".zshrc").exists() or os.environ.get("SHELL", "").endswith("zsh"):
            rcs.append(Path.home() / ".zshrc")
        for rc in rcs:
            poner_bloque(rc, bloque)
    print()
    print("Repositorios que encontrará aquí:")
    for nombre, ruta in repositorios():
        marca = "✓" if (ruta / ".git").exists() else T + "·"
        print(f"  {marca} {nombre:<18} {ruta}{R}")
    print()
    print(f"Listo. Abre un terminal nuevo y escribe {B}aldia{R}.")


# ---- Entrada ----------------------------------------------------------------
def main():
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return
    if args and args[0] == "--instalar":
        instalar()
        return
    solo_mirar = bool(args) and args[0] == "--estado"
    if args and args[0].startswith("--") and not solo_mirar:
        print(f"Opción desconocida: {args[0]}  (aldia --help)")
        sys.exit(1)

    ahora = dt.datetime.now()
    mensaje = (" ".join(args) if args and not solo_mirar
               else f"aldia: {platform.node() or 'equipo'} {ahora:%Y-%m-%d %H:%M}")
    print()
    print(f"{B}{'Estado' if solo_mirar else 'Al día'} · {ahora:%H:%M}{R}")
    resultados = [poner_al_dia(n, r, mensaje, solo_mirar) for n, r in repositorios()]
    print()
    if "error" in resultados:
        print(f"{Rj}Algo ha quedado a medias: mira las líneas con ✗.{R}")
    elif not solo_mirar:
        print(f"{V}Todo al día.{R}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrumpido. Lo que ya estaba hecho, hecho está; vuelve a ejecutar aldia.")
