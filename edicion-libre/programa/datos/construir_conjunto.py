"""Construye el conjunto de evaluación CAD-LLMIA de 60 casos auditables."""

import hashlib
import json
from pathlib import Path


BASICOS = [
    ("prisma", "Crea un cubo macizo de 20 mm de lado centrado en el origen y alineado con los ejes X, Y y Z.", "Una primitiva con una cota."),
    ("prisma", "Crea un bloque macizo de 40 mm en X, 25 mm en Y y 12 mm en Z, centrado en el origen, con caras paralelas a los planos coordenados.", "Una primitiva con tres cotas directas."),
    ("placa", "Crea una placa rectangular maciza de 60 mm en X, 35 mm en Y y 4 mm de espesor en Z, centrada en el origen.", "Prisma delgado con cotas explícitas."),
    ("barra", "Crea una barra prismática maciza de sección cuadrada 12 × 12 mm y longitud 55 mm a lo largo de Z, centrada en el origen.", "Una primitiva alargada."),
    ("cilindro", "Crea un cilindro macizo de diámetro 20 mm y altura 30 mm, coaxial con Z y centrado en el origen.", "Cilindro con diámetro y altura directos."),
    ("disco", "Crea un disco macizo de diámetro 50 mm y espesor 5 mm, coaxial con Z y centrado en el origen.", "Cilindro plano con dos cotas."),
    ("arandela", "Crea una arandela de diámetro exterior 40 mm, agujero pasante coaxial de diámetro 16 mm y espesor 5 mm. Centra la pieza en el origen con eje Z.", "Un sólido de revolución y una sustracción coaxial."),
    ("anillo", "Crea un anillo de diámetro exterior 60 mm, diámetro interior pasante 40 mm y altura 8 mm, centrado en el origen y coaxial con Z.", "Anillo con dos diámetros y espesor."),
    ("placa_perforada", "Crea una placa maciza de 50 × 30 × 8 mm en X, Y, Z, centrada en el origen, con un agujero circular pasante de diámetro 10 mm centrado y paralelo a Z.", "Un prisma y una perforación."),
    ("cilindro_perforado", "Crea un cilindro de diámetro 32 mm y altura 20 mm, centrado en el origen y coaxial con Z. Practica un agujero axial pasante de diámetro 8 mm.", "Un cilindro y una perforación."),
    ("placa_perforada", "Crea una placa rectangular de 45 × 28 × 6 mm centrada en el origen. Añade un agujero pasante de diámetro 6 mm paralelo a Z, ubicado en X = 10 mm e Y = 0 mm.", "Perforación desplazada con coordenadas explícitas."),
    ("placa_perforada", "Crea una placa cuadrada de 36 × 36 × 5 mm centrada en el origen. Haz un agujero pasante de diámetro 8 mm paralelo a Z en el centro.", "Sustracción circular centrada."),
    ("eje_escalonado", "Crea un eje macizo coaxial con Z: cilindro inferior de diámetro 20 mm y altura 20 mm desde Z = 0 hasta Z = 20 mm, unido a un cilindro superior de diámetro 12 mm y altura 15 mm desde Z = 20 hasta Z = 35 mm. Debe quedar un solo sólido.", "Unión de dos cilindros coaxiales."),
    ("resalte", "Crea una placa base de 40 × 30 × 5 mm centrada en X e Y, con su cara inferior en Z = 0. Une en su centro un resalte cilíndrico de diámetro 12 mm y altura 8 mm que comienza en Z = 5 mm. Debe quedar un solo sólido.", "Unión sencilla de dos primitivas."),
    ("tubo", "Crea un tubo cilíndrico de diámetro exterior 30 mm, diámetro interior pasante 20 mm y longitud 40 mm a lo largo de Z. Centra el tubo en el origen.", "Sustracción coaxial en una barra tubular."),
    ("marco", "Crea un tubo prismático de sección exterior cuadrada 40 × 40 mm, sección interior cuadrada 28 × 28 mm y altura 20 mm. Ambos cuadrados están centrados en XY y el hueco atraviesa Z por completo; centra la pieza en el origen.", "Una sustracción prismática centrada."),
    ("cilindro_perforado", "Crea un disco macizo de diámetro 45 mm y espesor 8 mm, centrado en el origen, con un agujero axial pasante de diámetro 5 mm.", "Disco con taladro axial sencillo."),
    ("bloque_rebajado", "Crea un bloque de 50 × 30 × 10 mm centrado en el origen. Retira un bolsillo rectangular de 18 × 12 mm, centrado en XY, desde la cara superior hasta 4 mm de profundidad; conserva un fondo macizo.", "Una cavidad ciega rectangular."),
    ("brida_simple", "Crea un disco de diámetro 55 mm y espesor 7 mm, centrado en el origen, con un único agujero pasante de diámetro 7 mm paralelo a Z en X = 18 mm, Y = 0 mm.", "Una perforación excéntrica."),
    ("soporte_escalon", "Crea una base maciza de 45 × 25 × 6 mm centrada en X e Y con cara inferior en Z = 0. Une sobre su mitad derecha, desde X = 0 hasta X = 22,5 mm, un bloque de 22,5 × 25 × 8 mm que comienza en Z = 6 mm. El resultado es un solo sólido escalonado.", "Unión ortogonal de dos prismas."),
]


INTERMEDIOS = [
    ("placa_patron", "Crea una placa de 70 × 50 × 8 mm centrada en el origen. Haz cuatro agujeros pasantes de diámetro 6 mm paralelos a Z en (X,Y) = (±25, ±15) mm, uno en cada combinación de signos. Sin chaflanes.", "Patrón de cuatro taladros dependiente de separaciones."),
    ("placa_patron", "Crea una placa de 80 × 40 × 6 mm centrada en el origen. Haz un agujero central pasante de diámetro 12 mm y dos agujeros pasantes de diámetro 5 mm en X = −28 y +28 mm, Y = 0; todos paralelos a Z.", "Tres cortes con posiciones relacionadas."),
    ("brida", "Crea una brida cilíndrica de diámetro 70 mm y espesor 10 mm con cara inferior en Z = 0. Une un resalte coaxial de diámetro 28 mm y altura 12 mm sobre la cara superior. Perfora un agujero axial pasante de diámetro 12 mm que atraviese ambos cuerpos. Un solo sólido.", "Unión y perforación en dos alturas."),
    ("brida", "Crea una brida de diámetro 80 mm y espesor 8 mm, centrada en XY con fondo en Z = 0. Practica cuatro agujeros pasantes de diámetro 6 mm en un círculo de centros de diámetro 60 mm, ubicados en los ejes X e Y, y un agujero central de diámetro 18 mm.", "Patrón polar y agujero central."),
    ("eje_escalonado", "Crea un eje coaxial con Z formado por tres tramos contiguos: diámetro 18 mm de Z = 0 a 20, diámetro 24 mm de Z = 20 a 28 y diámetro 12 mm de Z = 28 a 48. Añade un taladro axial pasante de diámetro 5 mm. Un solo sólido.", "Tres diámetros y perforación común."),
    ("caja_abierta", "Crea una caja rectangular abierta por arriba con exterior de 60 × 40 × 25 mm, base en Z = 0, paredes de 4 mm y fondo de 4 mm. La cavidad interior mide 52 × 32 mm en XY y va de Z = 4 a Z = 25 mm; centra X e Y.", "Cavidad con espesores y profundidad derivados."),
    ("placa_cajeada", "Crea un bloque de 65 × 45 × 14 mm centrado en X e Y, con base en Z = 0. Corta un bolsillo superior de 35 × 20 mm centrado en XY y profundidad 6 mm. Añade un taladro pasante de diámetro 8 mm en X = −25 mm, Y = 0.", "Bolsillo ciego y taladro fuera de él."),
    ("soporte_L", "Crea un soporte en L como un único sólido: base horizontal 60 × 30 × 6 mm con X e Y centrados y base en Z = 0; placa vertical de 6 mm en X, 30 mm en Y y 28 mm en Z, unida en el extremo X = −30 mm y desde Z = 6 hasta Z = 34 mm. Añade dos agujeros pasantes de diámetro 5 mm en la base, paralelos a Z, en X = 10 y 22 mm, Y = 0.", "Unión ortogonal y perforación doble."),
    ("tubo_transversal", "Crea un tubo de diámetro exterior 34 mm, diámetro interior axial 18 mm y longitud 50 mm sobre Z, centrado en el origen. Añade una perforación transversal pasante de diámetro 6 mm paralela a X, cuyo eje cruza (Y,Z) = (0,10) mm.", "Perforaciones en ejes distintos."),
    ("disco_patron", "Crea un disco de diámetro 65 mm y espesor 9 mm centrado en el origen. Abre seis agujeros pasantes de diámetro 5 mm a radio 24 mm del centro, separados cada 60 grados y paralelos a Z. Deja intacto el centro.", "Patrón angular de seis agujeros."),
    ("placa_resalte", "Crea una placa base 70 × 40 × 6 mm centrada en XY con base en Z = 0. Une un resalte central de diámetro 22 mm y altura 10 mm sobre ella. Haz un agujero axial pasante de diámetro 8 mm en el resalte y dos agujeros de diámetro 5 mm en X = ±25 mm, Y = 0, todos atravesando la placa.", "Unión y tres taladros con longitudes distintas."),
    ("mordaza", "Crea un bloque de 60 × 30 × 20 mm centrado en XY con base en Z = 0. Retira una ranura abierta central de 20 mm en X, 30 mm en Y y profundidad 10 mm desde la cara superior. Añade dos agujeros pasantes de diámetro 5 mm paralelos a Z en X = ±22 mm, Y = 0.", "Ranura y dos taladros fuera de ella."),
    ("eje_con_brida", "Crea un eje coaxial con Z de diámetro 16 mm y longitud 50 mm de Z = 0 a 50 mm. Une una brida de diámetro 40 mm y espesor 6 mm desde Z = 18 hasta Z = 24 mm. Practica un agujero axial pasante de diámetro 6 mm en toda la pieza.", "Brida intermedia y perforación común."),
    ("carcasa_cilindrica", "Crea una copa cilíndrica abierta arriba: exterior de diámetro 50 mm y altura 30 mm desde Z = 0, pared de 4 mm y fondo de 5 mm. El hueco interior tiene diámetro 42 mm y va de Z = 5 a Z = 30 mm. Agrega un agujero pasante de diámetro 8 mm en el centro del fondo.", "Cavidad, pared, fondo y taladro."),
    ("placa_escalonada", "Crea una placa 80 × 40 × 6 mm centrada en XY con base en Z = 0. Une dos resaltes rectangulares de 20 × 20 × 8 mm sobre ella, centrados en (X,Y) = (−25,0) y (25,0) mm. Perfora ambos resaltes y la base con agujeros coaxiales de diámetro 6 mm paralelos a Z.", "Dos salientes y dos taladros relacionados."),
    ("bastidor", "Crea un bastidor rectangular plano de dimensiones exteriores 80 × 50 × 8 mm, centrado en el origen. Vacía una ventana rectangular pasante de 60 × 30 mm centrada en XY. Añade dos agujeros pasantes de diámetro 4 mm en X = ±35 mm, Y = 0; deben permanecer dentro de los laterales del bastidor.", "Ventana y taladros en paredes estrechas."),
    ("brida_counterbore", "Crea un disco de diámetro 65 mm y espesor 12 mm con base en Z = 0, centrado en XY. Haz un agujero central pasante de diámetro 10 mm y un cajeado coaxial superior de diámetro 18 mm y profundidad 4 mm desde Z = 12 mm. Añade cuatro agujeros pasantes de diámetro 5 mm en (±20, ±20) mm.", "Taladro escalonado y patrón rectangular."),
    ("soporte_U", "Crea una base de 60 × 30 × 6 mm centrada en XY con base en Z = 0. Une dos paredes de 6 × 30 × 24 mm sobre los extremos X = ±27 mm, desde Z = 6 hasta Z = 30 mm, formando una U. Añade un agujero pasante de diámetro 6 mm paralelo a X en cada pared, con eje Y = 0, Z = 20 mm.", "Dos paredes y taladros transversales alineados."),
    ("polea_simple", "Crea una polea maciza de diámetro 60 mm y ancho 16 mm centrada en el origen, coaxial con Z. Practica un agujero axial pasante de diámetro 12 mm. Rebaja coaxialmente ambas caras con dos cavidades anulares de diámetro exterior 45 mm y diámetro interior 20 mm, cada una de 3 mm de profundidad; deja material en el cubo.", "Dos bolsillos anulares y perforación axial."),
    ("adaptador", "Crea una placa 70 × 50 × 8 mm centrada en XY con base en Z = 0. Une un cilindro de diámetro 24 mm y altura 14 mm en X = 10 mm, Y = 0, sobre la placa. Taladra el cilindro y la base con diámetro 8 mm, y añade dos agujeros pasantes de diámetro 5 mm en X = −25 mm, Y = ±15 mm.", "Resalte desplazado y patrón de montaje."),
]


COMPLEJOS = [
    ("brida_multinivel", "Crea una brida con disco base de diámetro 90 mm y espesor 10 mm desde Z = 0; resalte coaxial de diámetro 42 mm y altura 15 mm desde Z = 10; agujero axial pasante de diámetro 16 mm; cajeado coaxial superior de diámetro 28 mm y profundidad 5 mm; seis agujeros pasantes de diámetro 6 mm en radio 35 mm cada 60 grados. Un solo sólido sin chaflanes.", "Dos alturas, taladro escalonado y patrón polar de seis."),
    ("carcasa", "Crea una carcasa rectangular abierta arriba de exterior 90 × 60 × 35 mm, centrada en XY con base Z = 0, paredes de 5 mm y fondo de 6 mm. Añade cuatro resaltes interiores cilíndricos de diámetro 12 mm y altura 14 mm desde el fondo en (X,Y) = (±30, ±18) mm; perfora cada resalte y el fondo con agujero coaxial de diámetro 4 mm. Debe quedar un solo sólido.", "Espesores derivados, cuatro apoyos y cuatro taladros."),
    ("soporte_reforzado", "Crea un soporte en L: base 90 × 45 × 8 mm centrada en XY con base Z = 0; pared vertical de 8 mm en X y 45 mm en Y hasta Z = 50 mm ubicada en el extremo X negativo. Une dos nervios triangulares de espesor 6 mm paralelos a XZ en Y = ±14 mm, desde la base a la pared. Perfora la base con cuatro agujeros de diámetro 6 mm en (X,Y) = (±30, ±15) mm. Un solo sólido.", "Placas, nervios triangulares y patrón rectangular."),
    ("horquilla", "Crea una horquilla de bloque exterior 70 × 35 × 35 mm centrado en XY, base Z = 0. Abre desde arriba una ranura central de 22 mm en X que atraviese los 35 mm de Y y baje hasta Z = 12 mm, dejando dos orejas laterales de 24 mm en X. Taladra ambas orejas con un eje pasante paralelo a X de diámetro 8 mm a Y = 0, Z = 25 mm. Añade dos agujeros verticales de diámetro 5 mm en la base a X = ±28 mm, Y = 0.", "Ranura abierta, eje transversal y fijaciones."),
    ("disipador", "Crea un disipador como un solo sólido: base 80 × 50 × 6 mm centrada en XY con base Z = 0; ocho aletas paralelas a Y de 3 × 50 × 20 mm desde Z = 6, con centros X equiespaciados de −31,5 a +31,5 mm en pasos de 9 mm. Taladra la base con cuatro agujeros verticales de diámetro 4 mm en (X,Y) = (±36, ±20) mm, sin intersectar aletas.", "Ocho uniones finas y patrón de montaje."),
    ("eje_taladrado", "Crea un eje coaxial con Z formado por tramos contiguos: diámetro 24 mm de Z = 0 a 20, diámetro 36 mm de Z = 20 a 28, diámetro 18 mm de Z = 28 a 60 y diámetro 12 mm de Z = 60 a 72 mm. Practica un taladro axial pasante de diámetro 6 mm y dos taladros transversales de diámetro 5 mm paralelos a X en Z = 10 y 50 mm. Un solo sólido.", "Cuatro escalones y tres perforaciones en dos ejes."),
    ("adaptador_motor", "Crea una placa adaptadora circular de diámetro 100 mm y espesor 8 mm desde Z = 0, con resalte central de diámetro 45 mm y altura 12 mm. Abre agujero central pasante de diámetro 20 mm, cuatro agujeros de diámetro 6 mm en radio 35 mm a 0, 90, 180 y 270 grados y otros cuatro de diámetro 4 mm en radio 42 mm a 45, 135, 225 y 315 grados. Un solo sólido.", "Dos patrones polares desfasados y resalte perforado."),
    ("mordaza_escalonada", "Crea un bloque de 90 × 45 × 30 mm centrado en XY, base Z = 0. Retira una cavidad superior central de 40 × 20 mm y profundidad 12 mm; prolonga la cavidad con una ranura pasante en Y de 12 mm de ancho en X y profundidad adicional hasta Z = 10 mm. Añade cuatro agujeros verticales pasantes de diámetro 6 mm en (±35, ±15) mm. Conserva un solo sólido.", "Bolsillos de dos profundidades y fijaciones."),
    ("carcasa_cilindrica", "Crea una carcasa cilíndrica abierta arriba: exterior de diámetro 80 mm y altura 40 mm desde Z = 0, pared de 5 mm y fondo de 8 mm. Une un reborde exterior coaxial de diámetro 95 mm y espesor 6 mm desde Z = 34 hasta 40 mm. Abre cuatro agujeros verticales pasantes de diámetro 5 mm en radio 42 mm a ángulos 0, 90, 180 y 270 grados, atravesando el reborde. Un solo sólido.", "Cavidad, reborde y patrón de tornillos."),
    ("placa_con_bosses", "Crea una placa de 100 × 70 × 8 mm centrada en XY con base Z = 0. Une cuatro apoyos cilíndricos de diámetro 16 mm y altura 12 mm en (X,Y) = (±35, ±22) mm; taladra cada apoyo y la placa con diámetro 5 mm. Añade un bolsillo central ciego de 45 × 25 mm y profundidad 3 mm desde la cara superior de la placa, sin tocar los apoyos.", "Cuatro salientes perforados y bolsillo independiente."),
    ("polea_doble", "Crea una polea coaxial con Z de diámetro exterior 85 mm y ancho 22 mm centrada en el origen. Deja un cubo coaxial de diámetro 32 mm. Rebaja en cada cara una cavidad anular entre diámetros 40 y 70 mm hasta 5 mm de profundidad, preservando el cubo y el aro exterior. Practica un agujero axial pasante de diámetro 12 mm y cuatro agujeros pasantes de diámetro 5 mm en radio 25 mm cada 90 grados.", "Dos rebajes anulares, cubo y perforaciones."),
    ("plataforma_escalonada", "Crea una base 100 × 60 × 8 mm centrada en XY con base Z = 0. Une una plataforma superior de 60 × 40 × 12 mm centrada sobre ella desde Z = 8 hasta 20 mm y un resalte cilíndrico central de diámetro 24 mm y altura 10 mm desde Z = 20. Taladra el centro con diámetro 10 mm atravesando todo el conjunto y agrega cuatro agujeros verticales de diámetro 6 mm en la base en (±42, ±22) mm.", "Tres niveles y cinco taladros de longitudes distintas."),
    ("soporte_doble", "Crea una base 90 × 50 × 8 mm centrada en XY con base Z = 0. Une dos paredes verticales de 8 × 50 × 38 mm en los extremos X = ±41 mm desde Z = 8. Añade una traviesa superior 90 × 8 × 8 mm centrada en Y y situada de Z = 38 a 46 mm, uniendo ambas paredes. Perfora las paredes con agujeros coaxiales de diámetro 8 mm paralelos a X, a Y = 0 y Z = 25 mm. Un solo sólido.", "Estructura cerrada de cuatro miembros y agujeros alineados."),
    ("acople", "Crea un acople coaxial con Z: cuerpo central de diámetro 42 mm y longitud 35 mm desde Z = 5 hasta 40; dos bridas de diámetro 70 mm y espesor 5 mm en Z = 0..5 y Z = 40..45. Abre taladro axial pasante de diámetro 18 mm y cuatro agujeros verticales de diámetro 6 mm en cada brida, ubicados a radio 28 mm sobre los ejes X/Y; ningún agujero de brida debe atravesar el cuerpo central.", "Dos bridas, eje hueco y patrones restringidos por altura."),
    ("base_nervada", "Crea una base 100 × 80 × 8 mm centrada en XY con base Z = 0. Une un resalte central de 30 × 25 × 15 mm desde Z = 8. Une cuatro nervios rectangulares de 10 mm de ancho, 20 mm de largo y 10 mm de alto que conectan el resalte con las direcciones ±X y ±Y sobre la base. Taladra el resalte con diámetro 10 mm de forma vertical y añade cuatro agujeros de montaje de diámetro 5 mm en (±42, ±32) mm.", "Resalte, cuatro nervios y cinco perforaciones."),
    ("carcasa_paredes", "Crea una carcasa abierta superior de dimensiones exteriores 110 × 70 × 40 mm, centrada en XY con base Z = 0, paredes de 5 mm y fondo de 6 mm. Abre dos ventanas pasantes de 25 × 12 mm en las paredes opuestas normales a Y, centradas en X = 0 y Z = 24 mm. Añade cuatro agujeros verticales de diámetro 5 mm en el fondo en (X,Y) = (±40, ±24) mm. Un solo sólido.", "Cavidad, ventanas en paredes opuestas y fijaciones."),
    ("brida_ovalada", "Crea una base ovalada como unión de un rectángulo de 60 × 40 × 10 mm y dos semicírculos de radio 20 mm en los extremos X, de modo que su largo total sea 100 mm; centra XY y coloca base Z = 0. Une un resalte cilíndrico central de diámetro 30 mm y altura 12 mm. Abre taladro axial pasante de diámetro 12 mm y dos agujeros de montaje de diámetro 7 mm en X = ±35 mm, Y = 0.", "Perfil no circular compuesto, resalte y taladros."),
    ("soporte_canal", "Crea un perfil de canal de 100 mm de longitud en X, ancho exterior 50 mm en Y y altura exterior 35 mm en Z, centrado en X/Y con base Z = 0. El fondo tiene 7 mm y las dos paredes laterales en Y tienen 6 mm. Une dos refuerzos transversales de 6 mm de espesor en X ubicados en X = ±30 mm, que conecten ambas paredes hasta Z = 20 mm. Practica cuatro agujeros verticales de diámetro 5 mm en el fondo, en (X,Y) = (±42, ±15) mm.", "Canal, dos travesaños y cuatro taladros."),
    ("disco_radial", "Crea un disco base de diámetro 100 mm y espesor 8 mm desde Z = 0. Une seis radios rectangulares horizontales de longitud 30 mm, ancho 8 mm y altura 10 mm desde Z = 8, orientados radialmente cada 60 grados desde un cubo central de diámetro 28 mm y altura 10 mm. Une un aro exterior de diámetro exterior 100 mm e interior 80 mm desde Z = 8 a Z = 18 mm. Abre agujero axial pasante de diámetro 12 mm. Un solo sólido.", "Patrón radial, cubo y aro con dependencias de unión."),
    ("adaptador_multiperfil", "Crea una base rectangular 110 × 80 × 8 mm centrada en XY con base Z = 0. Une dos cilindros de diámetro 32 mm y altura 16 mm en centros X = ±30 mm, Y = 0. Abre agujeros axiales pasantes de diámetros 12 mm en el cilindro izquierdo y 16 mm en el derecho. Añade cuatro agujeros verticales de montaje de diámetro 6 mm en (X,Y) = (±45, ±30) mm y un bolsillo superior de 20 × 14 mm y profundidad 4 mm centrado entre los cilindros.", "Dos interfaces de distinto diámetro, patrón y bolsillo."),
]


def construir_casos() -> list[dict]:
    casos = []
    for prefijo, nivel, origen in (
        ("B", "basico", BASICOS),
        ("I", "intermedio", INTERMEDIOS),
        ("C", "complejo", COMPLEJOS),
    ):
        assert len(origen) == 20, f"El nivel {nivel} debe tener exactamente veinte casos"
        for indice, (familia, descripcion, fundamento) in enumerate(origen, 1):
            casos.append(
                {
                    "codigo": f"{prefijo}{indice:02d}",
                    "nivel": nivel,
                    "familia": familia,
                    "fundamento": fundamento,
                    "descripcion": descripcion,
                    "especificacion": {"unidad": "mm", "solidos_esperados": 1},
                }
            )
    return casos


def escribir_conjunto() -> None:
    datos = {
        "nombre": "CAD-LLMIA-60",
        "version": "1.0.0",
        "finalidad": "evaluacion",
        "unidad": "mm",
        "casos": construir_casos(),
    }
    ruta = Path(__file__).with_name("prompts_60_v1.json")
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(datos['casos'])} casos; SHA-256 {hashlib.sha256(ruta.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    escribir_conjunto()
