"""Compara la estructura de recibos de nómina (CFDI 4.0 + nómina 1.2).

Uso:
    python comparar_tags.py xmls
        Compara cada recibo con el anterior DE LA MISMA EMPRESA
        (ordenados por fecha de pago).

    python comparar_tags.py xmls\\anterior.xml xmls\\nuevo.xml
        Compara dos recibos específicos.

Avisa de:
  - tags nuevos o que desaparecieron
  - atributos nuevos o que desaparecieron dentro de un mismo tag
  - cambios de versión (CFDI, nómina, timbre)
  - percepciones, deducciones y otros pagos nuevos o ausentes
"""
import sys
from pathlib import Path
import xml.etree.ElementTree as ET

from leer_nomina import leer_recibo, local


def estructura(ruta):
    """Devuelve (atributos por ruta de tag, versiones por ruta de tag)."""
    raiz = ET.parse(ruta).getroot()
    atributos = {}
    versiones = {}

    def recorrer(nodo, camino):
        actual = f"{camino}/{local(nodo.tag)}"
        nombres = atributos.setdefault(actual, set())
        for clave, valor in nodo.attrib.items():
            nombre = local(clave)
            nombres.add(nombre)
            if nombre == "Version":
                versiones[actual] = valor
        for hijo in nodo:
            recorrer(hijo, actual)

    recorrer(raiz, "")
    return atributos, versiones


def orden(clave):
    """Para ordenar (tipo, clave) aunque alguno venga vacío."""
    return (clave[0] or "", clave[1] or "")


def comparar_estructura(ruta_a, ruta_b):
    attr_a, ver_a = estructura(ruta_a)
    attr_b, ver_b = estructura(ruta_b)
    cambios = []

    for camino in sorted(attr_b.keys() - attr_a.keys()):
        cambios.append(f"+ Tag nuevo: {camino}")
    for camino in sorted(attr_a.keys() - attr_b.keys()):
        cambios.append(f"- Tag que desapareció: {camino}")

    for camino in sorted(attr_a.keys() & attr_b.keys()):
        for nombre in sorted(attr_b[camino] - attr_a[camino]):
            cambios.append(f"+ Atributo nuevo en {camino}: {nombre}")
        for nombre in sorted(attr_a[camino] - attr_b[camino]):
            cambios.append(f"- Atributo que desapareció en {camino}: {nombre}")

    for camino in sorted(ver_a.keys() & ver_b.keys()):
        if ver_a[camino] != ver_b[camino]:
            cambios.append(f"~ Cambió la versión en {camino}: {ver_a[camino]} -> {ver_b[camino]}")

    return cambios


def comparar_conceptos(rec_a, rec_b):
    cambios = []
    grupos = (
        ("Percepción", "percepciones"),
        ("Deducción", "deducciones"),
        ("Otro pago", "otros_pagos"),
    )
    for etiqueta, campo in grupos:
        a = {(x["tipo"], x["clave"]): x["concepto"] for x in rec_a[campo]}
        b = {(x["tipo"], x["clave"]): x["concepto"] for x in rec_b[campo]}

        for k in sorted(b.keys() - a.keys(), key=orden):
            aviso = "   <- clasifícala en categoria_deduccion" if etiqueta == "Deducción" else ""
            cambios.append(f"+ {etiqueta} nueva: [{k[0]}] {k[1]} {b[k]}{aviso}")
        for k in sorted(a.keys() - b.keys(), key=orden):
            cambios.append(f"- {etiqueta} que ya no aparece: [{k[0]}] {k[1]} {a[k]}")
        for k in sorted(a.keys() & b.keys(), key=orden):
            if a[k] != b[k]:
                cambios.append(f"~ {etiqueta} cambió de nombre [{k[0]}] {k[1]}: {a[k]} -> {b[k]}")

    return cambios


def imprimir(ruta_a, ruta_b):
    rec_a = leer_recibo(ruta_a)
    rec_b = leer_recibo(ruta_b)
    misma_empresa = rec_a["emisor_rfc"] == rec_b["emisor_rfc"]

    print(f"Anterior: {Path(ruta_a).name}  (pago {rec_a['fecha_pago']})")
    print(f"Nuevo:    {Path(ruta_b).name}  (pago {rec_b['fecha_pago']})")
    if not misma_empresa:
        print("AVISO: son de empresas distintas; la estructura se compara, pero las claves "
              "de percepciones y deducciones no son comparables entre empresas.")

    print("Estructura del XML:")
    cambios = comparar_estructura(ruta_a, ruta_b)
    if cambios:
        for linea in cambios:
            print("  " + linea)
    else:
        print("  Sin cambios.")

    if misma_empresa:
        print("Conceptos:")
        cambios = comparar_conceptos(rec_a, rec_b)
        if cambios:
            for linea in cambios:
                print("  " + linea)
        else:
            print("  Sin cambios.")


def pares_por_empresa(carpeta):
    """Ordena los recibos por empresa y fecha de pago, y devuelve los pares
    (anterior, nuevo) de la misma empresa."""
    recibos = []
    for archivo in sorted(Path(carpeta).glob("*.xml")):
        try:
            r = leer_recibo(archivo)
        except Exception as error:
            print(f"ERROR en {archivo.name}: {error}")
            continue
        recibos.append((r["emisor_rfc"] or "", r["fecha_pago"] or "", archivo))
    recibos.sort()

    pares = []
    for anterior, nuevo in zip(recibos, recibos[1:]):
        if anterior[0] == nuevo[0]:
            pares.append((anterior[2], nuevo[2]))
    return pares


if __name__ == "__main__":
    args = sys.argv[1:]

    if len(args) == 1 and Path(args[0]).is_dir():
        pares = pares_por_empresa(args[0])
        if not pares:
            print("Se necesitan al menos dos recibos de la misma empresa en la carpeta.")
        for anterior, nuevo in pares:
            imprimir(anterior, nuevo)
            print("-" * 60)
    elif len(args) == 2:
        imprimir(args[0], args[1])
    else:
        print("Uso: python comparar_tags.py <carpeta>")
        print("     python comparar_tags.py <anterior.xml> <nuevo.xml>")
        sys.exit(1)