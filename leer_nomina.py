"""Lector de recibos de nómina (CFDI 4.0 con complemento de nómina 1.2).

Uso:
    python leer_nomina.py xmls\\recibo.xml      (un archivo)
    python leer_nomina.py xmls                  (todos los .xml de una carpeta)

Lee los datos que se guardarán en la base de datos y valida que las
líneas sumen lo que declaran los totales del XML.
Lee los datos de la empresa (emisor) para distinguir entre varias nóminas.
No lee los datos personales del trabajador: RFC, CURP, NSS, nombre ni cuenta bancaria.
"""
import sys
from decimal import Decimal
from pathlib import Path
import xml.etree.ElementTree as ET


def local(tag):
    """Quita el namespace: '{http://...}Nomina' -> 'Nomina'."""
    return tag.split("}")[-1]


def dec(valor):
    """Convierte un atributo a Decimal. Si no existe, devuelve 0."""
    return Decimal(valor) if valor not in (None, "") else Decimal("0")


def leer_recibo(ruta):
    """Lee un XML de nómina y devuelve un diccionario con sus datos."""
    ruta = Path(ruta)
    raiz = ET.parse(ruta).getroot()  # Comprobante

    recibo = {
        "archivo_origen": ruta.name,
        "version_cfdi": raiz.get("Version"),
        "serie": raiz.get("Serie"),
        "folio": raiz.get("Folio"),
        "moneda": raiz.get("Moneda"),
        "emisor_rfc": None,
        "emisor_nombre": None,
        "emisor_regimen_fiscal": None,
        "registro_patronal": None,
        "fecha_comprobante": raiz.get("Fecha"),
        "subtotal": dec(raiz.get("SubTotal")),
        "descuento": dec(raiz.get("Descuento")),
        "total": dec(raiz.get("Total")),
        "percepciones": [],
        "deducciones": [],
        "otros_pagos": [],
    }

    # Empresa: Emisor del Comprobante (solo hijos directos de la raíz,
    # para no confundirlo con el Emisor de la nómina).
    for hijo in raiz:
        if local(hijo.tag) == "Emisor":
            recibo["emisor_rfc"] = hijo.get("Rfc")
            recibo["emisor_nombre"] = hijo.get("Nombre")
            recibo["emisor_regimen_fiscal"] = hijo.get("RegimenFiscal")

    nomina = None
    for nodo in raiz.iter():
        nombre = local(nodo.tag)
        if nombre == "TimbreFiscalDigital":
            recibo["uuid"] = nodo.get("UUID")
        elif nombre == "Nomina":
            nomina = nodo

    if nomina is None:
        raise ValueError(f"{ruta.name}: no tiene complemento de nómina")

    recibo.update({
        "tipo_nomina": nomina.get("TipoNomina"),
        "fecha_pago": nomina.get("FechaPago"),
        "fecha_inicial_pago": nomina.get("FechaInicialPago"),
        "fecha_final_pago": nomina.get("FechaFinalPago"),
        "num_dias_pagados": dec(nomina.get("NumDiasPagados")),
        "total_percepciones": dec(nomina.get("TotalPercepciones")),
        "total_deducciones": dec(nomina.get("TotalDeducciones")),
        "total_otros_pagos": dec(nomina.get("TotalOtrosPagos")),
        "total_gravado": Decimal("0"),
        "total_exento": Decimal("0"),
        "total_otras_deducciones": Decimal("0"),
        "total_impuestos_retenidos": Decimal("0"),
        "periodicidad_pago": None,
        "salario_base_cot_apor": None,
        "salario_diario_integrado": None,
    })

    # Se recorren solo los hijos directos de Nomina. Así no se confunde
    # el Emisor/Receptor de la nómina con los del Comprobante.
    for hijo in nomina:
        nombre = local(hijo.tag)

        if nombre == "Emisor":
            recibo["registro_patronal"] = hijo.get("RegistroPatronal")

        elif nombre == "Receptor":
            recibo["periodicidad_pago"] = hijo.get("PeriodicidadPago")
            recibo["salario_base_cot_apor"] = dec(hijo.get("SalarioBaseCotApor"))
            recibo["salario_diario_integrado"] = dec(hijo.get("SalarioDiarioIntegrado"))

        elif nombre == "Percepciones":
            recibo["total_gravado"] = dec(hijo.get("TotalGravado"))
            recibo["total_exento"] = dec(hijo.get("TotalExento"))
            for p in hijo:
                if local(p.tag) == "Percepcion":
                    recibo["percepciones"].append({
                        "tipo": p.get("TipoPercepcion"),
                        "clave": p.get("Clave"),
                        "concepto": p.get("Concepto"),
                        "importe_gravado": dec(p.get("ImporteGravado")),
                        "importe_exento": dec(p.get("ImporteExento")),
                    })

        elif nombre == "Deducciones":
            recibo["total_otras_deducciones"] = dec(hijo.get("TotalOtrasDeducciones"))
            recibo["total_impuestos_retenidos"] = dec(hijo.get("TotalImpuestosRetenidos"))
            for d in hijo:
                if local(d.tag) == "Deduccion":
                    recibo["deducciones"].append({
                        "tipo": d.get("TipoDeduccion"),
                        "clave": d.get("Clave"),
                        "concepto": d.get("Concepto"),
                        "importe": dec(d.get("Importe")),
                    })

        elif nombre == "OtrosPagos":
            for o in hijo:
                if local(o.tag) == "OtroPago":
                    subsidio = Decimal("0")
                    for s in o:
                        if local(s.tag) == "SubsidioAlEmpleo":
                            subsidio = dec(s.get("SubsidioCausado"))
                    recibo["otros_pagos"].append({
                        "tipo": o.get("TipoOtroPago"),
                        "clave": o.get("Clave"),
                        "concepto": o.get("Concepto"),
                        "importe": dec(o.get("Importe")),
                        "subsidio_causado": subsidio,
                    })

    return recibo


def validar(recibo):
    """Compara las líneas contra los totales del XML.
    Devuelve una lista de avisos; si está vacía, todo cuadra."""
    avisos = []

    suma_percep = sum(
        (p["importe_gravado"] + p["importe_exento"] for p in recibo["percepciones"]),
        Decimal("0"),
    )
    suma_deduc = sum((d["importe"] for d in recibo["deducciones"]), Decimal("0"))
    suma_otros = sum((o["importe"] for o in recibo["otros_pagos"]), Decimal("0"))

    def revisar(descripcion, calculado, declarado):
        if calculado != declarado:
            avisos.append(f"{descripcion}: calculado {calculado} vs declarado {declarado}")

    revisar("Percepciones (líneas vs TotalPercepciones)", suma_percep, recibo["total_percepciones"])
    revisar("Gravado + exento vs líneas de percepciones",
            recibo["total_gravado"] + recibo["total_exento"], suma_percep)
    revisar("Deducciones (líneas vs TotalDeducciones)", suma_deduc, recibo["total_deducciones"])
    revisar("Otras deducciones + impuestos retenidos vs TotalDeducciones",
            recibo["total_otras_deducciones"] + recibo["total_impuestos_retenidos"],
            recibo["total_deducciones"])
    revisar("Otros pagos (líneas vs TotalOtrosPagos)", suma_otros, recibo["total_otros_pagos"])
    revisar("SubTotal vs percepciones + otros pagos",
            recibo["subtotal"], recibo["total_percepciones"] + recibo["total_otros_pagos"])
    revisar("Descuento vs TotalDeducciones", recibo["descuento"], recibo["total_deducciones"])
    revisar("Total vs SubTotal - Descuento",
            recibo["total"], recibo["subtotal"] - recibo["descuento"])

    return avisos


def mostrar(recibo):
    """Imprime un resumen del recibo."""
    uuid = recibo.get("uuid") or ""
    print(f"Archivo:        {recibo['archivo_origen']}")
    print(f"Empresa:        {recibo['emisor_nombre']} ({recibo['emisor_rfc']})")
    print(f"UUID:           {uuid[:8]}...")
    print(f"Periodo:        {recibo['fecha_inicial_pago']} a {recibo['fecha_final_pago']}"
          f"  (pago: {recibo['fecha_pago']})")
    print(f"{'Percepciones:':<37}{'Gravado':>12} {'Exento':>12} {'Total':>12}")
    for p in recibo["percepciones"]:
        g = p["importe_gravado"]
        e = p["importe_exento"]
        print(f"  [{p['tipo']}] {p['clave']} {p['concepto'][:24]:<24} {g:>12,.2f} {e:>12,.2f} {g + e:>12,.2f}")
    print(f"  {'Totales':<34} {recibo['total_gravado']:>12,.2f} "
          f"{recibo['total_exento']:>12,.2f} {recibo['total_percepciones']:>12,.2f}")
    print("Deducciones:")
    for d in recibo["deducciones"]:
        print(f"  [{d['tipo']}] {d['clave']} {d['concepto']:<28} {d['importe']:>12,.2f}")
    if recibo["otros_pagos"]:
        print("Otros pagos:")
        for o in recibo["otros_pagos"]:
            print(f"  [{o['tipo']}] {o['clave']} {o['concepto']:<28} {o['importe']:>12,.2f}")
    print(f"Total percepciones: {recibo['total_percepciones']:>12,.2f}")
    print(f"Total deducciones:  {recibo['total_deducciones']:>12,.2f}")
    print(f"Neto pagado:        {recibo['total']:>12,.2f}")

    avisos = validar(recibo)
    if avisos:
        print("AVISOS DE VALIDACIÓN:")
        for aviso in avisos:
            print("  -", aviso)
    else:
        print("Validación: los totales cuadran.")


def archivos_xml(argumento):
    """Devuelve la lista de XMLs de un archivo o de una carpeta."""
    ruta = Path(argumento)
    if ruta.is_dir():
        return sorted(ruta.glob("*.xml"))
    return [ruta]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python leer_nomina.py <archivo.xml | carpeta>")
        sys.exit(1)

    for archivo in archivos_xml(sys.argv[1]):
        try:
            mostrar(leer_recibo(archivo))
        except Exception as error:
            print(f"ERROR en {archivo.name}: {error}")
        print("-" * 60)