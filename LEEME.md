# Acomoda — guía de uso

**Acomoda** (versión 3) **diseña los racks** de un almacén o una tienda y ubica en ellos los productos usando
**un solo modelo de optimización** (programación lineal entera resuelta con PuLP + CBC). Usa tres entradas que usted
sube —**catálogo con medidas**, **plano o medidas del local** y **reporte de ventas**—, aplica las **normas peruanas**
que ya vienen incluidas, **costea** la propuesta y **demuestra con datos y estadística** si resuelve el problema.
**No hace falta medir estantes:** el programa propone qué tipos de rack usar, cuántos, de qué medidas y dónde.

Proyecto final del curso *Modelos Cuantitativos y de Optimización* (Administración de Empresas).
Sirve para cualquier empresa; el caso de prueba es una tienda de Juliaca.

---

## 1. Instalación

### Opción A — Instalador para compartir (no necesita Python ni internet)

1. Comparta **`Instalar_Acomoda.exe`**. En la otra computadora, ábralo y siga el asistente (no pide administrador).
2. Abra **Acomoda** desde el escritorio o el menú Inicio. Se abre una ventana negra (no la cierre) y luego el navegador con la app.
3. Todo funciona **sin internet** y queda solo en esa computadora, en la carpeta `Acomoda_datos` junto al `.exe`.
   Al volver a abrir Acomoda continúa el último proyecto.
4. Para cerrar, cierre la ventana negra.

> Si Windows muestra «Windows protegió su PC», pulse «Más información» → «Ejecutar de todas formas»
> (el programa no está firmado digitalmente).

### Opción B — Desde el código (Python 3.11+)

```
pip install -r requirements.txt
streamlit run app.py
```

### Volver a construir el ejecutable y el instalador

```
pip install -r requirements.txt pyinstaller
pyinstaller empaquetado/acomoda.spec --noconfirm
"%LOCALAPPDATA%ProgramsInno Setup 6ISCC.exe" empaquetadoinstalador.iss
```

Los datos reales de `datos_entrada/` **no** se incluyen. Para incluirlos (botones «Usar el catálogo/reporte de prueba»),
antes de construir ejecute `set ACOMODA_INCLUIR_PRUEBA=1`; hágalo solo si puede compartir esos datos.

---

## 2. Cómo se usa: 8 pasos con compuertas

La barra lateral muestra los pasos con su estado: ✅ confirmado, ⚠️ confirmado con advertencias, ⏳ pendiente,
🔒 bloqueado. **No se puede abrir un paso si el anterior no está confirmado.** Antes de empezar, escriba su
nombre en «Responsable» (queda en el acta), elija el **perfil de rubro** y el **modo**:

- **Almacén (picking):** minimiza el recorrido ponderado por rotación (lo que más sale, más cerca del despacho y a la
  altura cómoda).
- **Tienda (exhibición):** maximiza margen × exposición (lo más rentable, a la altura de los ojos, en cabeceras y
  cerca de la caja).

Arriba de cada pantalla está el **índice de confiabilidad (0–100 %)**: el porcentaje de sus ventas en soles cuyos
productos tienen medidas reales, multiplicado por la precisión de la fuente del local (Excel o DXF 100 %,
imagen 80 %, local de ejemplo 50 %).

| Paso | Qué hace | Qué confirma usted |
|---|---|---|
| 1. Catálogo con magnitudes | Lee su catálogo, quita filas vacías, une códigos repetidos (suma el stock), adivina categorías por el nombre y reporta la calidad. | «Los datos del catálogo son correctos». |
| 2. Plano o medidas del local | Lee la plantilla Excel, un DXF o trazos sobre una imagen/PDF y muestra **«Esto es lo que entendí»**: resumen, plano 2D, 3D, advertencias y sus preferencias y presupuesto. Los estantes existentes son **opcionales**. | Las 4 casillas (dimensiones, puertas/salidas, «¿Los estantes existentes que declaré son correctos? (o no declaré ninguno)», advertencias). Con errores graves el botón no se activa. |
| 3. Reporte de ventas | Asistente de columnas, periodo, rotación, ABC, picos por mes, pares vendidos juntos. Descarta (e informa) las ventas de productos que no están en el catálogo. | Que la fecha de ejemplo y las cantidades se leyeron bien. |
| 4. Normativas | Panel de lectura con cada norma, la regla que produce en el modelo, su estado de verificación y el semáforo sobre su local. Pasillos, evacuación, cargas y alturas **dan forma a los racks candidatos**. | «Confirmo las normativas que se aplicarán». |
| 5. Diseñar y optimizar | Modo de diseño A/B/C, presupuesto, catálogo de racks editable, deslizador λ, tiempo límite. **Propuesta rápida** (heurística, segundos) y **propuesta completa** (modelo; el solver corre en un hilo aparte con barra de progreso). Muestra el diseño, la lista de compra y, si no cabe todo, alternativas con su costo. | «Acepto esta propuesta». |
| 6. Resultados | Vista 3D (racks propuestos en naranja, existentes en gris azulado), plano 2D, ubicaciones, antes/después, escenarios, sensibilidad de los pesos y reporte normativo. Cada vista se calcula solo al abrirla. | «He revisado los resultados». |
| 7. Evidencia | Planteamiento del problema con diagnóstico en cifras, simulación con **pedidos reales**, réplicas aleatorias, contraste de hipótesis, sensibilidad de las conclusiones, validación técnica, **veredicto** con semáforo y **límites de la evidencia**. | «Revisé la evidencia, el veredicto y sus límites». |
| 8. Costeo y entregables | Costeo editable (dos escenarios), informe gerencial Word/Excel, paquete del artículo, lista de compra, lista de reubicación, Excel de la propuesta, acta y 3D en HTML. | «Entregables revisados». |

**Para practicar sin datos propios:** en el Paso 1 pulse «Usar el catálogo de prueba», en el Paso 2 elija
«D. Local de ejemplo (EJEMPLO, NO ES REAL)» y en el Paso 3 «Usar el reporte de prueba».

---

## 3. Cómo llenar cada plantilla

Cada plantilla se descarga desde el programa y trae: hoja **INSTRUCCIONES**, hoja(s) de **datos** con listas
desplegables, hoja **EJEMPLO** (filas falsas) y encabezados de color:

- 🟧 **naranja = obligatoria** (si falta, la fila tiene error);
- 🟨 **amarillo = importante** (si falta, se estima y baja la confiabilidad);
- 🟦 **celeste = opcional**; ⬜ **gris = informativa** (el programa no la lee).

Al subirla, el programa revisa **celda por celda** y dice, por ejemplo: «Hoja DATOS, fila 37, columna `alto_cm`:
debe ser un número mayor que 0». Puede descargar el archivo con los errores **pintados de rojo**, corregirlo y
volver a subirlo. Las plantillas tienen versión: si sube una antigua, el programa la rechaza y le pide la nueva.

### 3.1 Catálogo (`plantilla_catalogo.xlsx`)

- Una fila por producto. Mida **una unidad** tal como va en el estante: `largo_cm` = frente, `ancho_cm` = fondo,
  `alto_cm` = altura parada; `peso_kg` con balanza (de cocina o de la tienda).
- Si el producto llega en caja del proveedor, llene `unidades_por_caja` y las medidas de la caja: en modo almacén
  se manipula la caja.
- `apilable`, `se_puede_girar`, `fragil`, `perecible`, `peligroso`, `valor_alto`: sí/no. Si no sabe, déjelo vacío
  (se propone un valor y se marca como estimado).
- `ubicacion_actual` (opcional, ej. `E1-N2-T1`): permite medir el «antes» real en lugar de uno simulado.
- **Plantilla prellenada:** si sube el catálogo de su sistema sin medidas, el programa genera la plantilla con sus
  productos **ordenados por ventas en soles** y le dice cuántos debe medir para cubrir el 80 % de las ventas.
  Mida esos primero.

### 3.2 Local (`plantilla_local.xlsx`) — cómo medir

1. Elija como **origen (0,0)** la esquina inferior izquierda del plano, mirando con la puerta principal abajo.
   **X** crece hacia la derecha y **Y** hacia arriba. Todo en **metros**.
2. Use huincha o medidor láser; mida dos veces cada distancia, desde muros terminados.
3. **Altura libre útil:** del piso a lo más bajo del techo (viga, luminaria, ducto, rociador).
4. Cada elemento se ubica por su esquina más cercana al origen (`x_m`, `y_m`) y su tamaño en X (`largo_m`) y en Y (`ancho_m`).
5. **ESTANTES_EXISTENTES (opcional):** llénela **solo** si tiene estantes que quiere conservar (modos B o C). Por
   cada uno: largo del frente, fondo, alto total, número de niveles, altura libre de cada nivel (`0.42;0.36;0.33`),
   capacidad por nivel (etiqueta del fabricante) y **orientación** del frente: 0 = mira hacia Y menor (abajo en el
   plano), 180 = hacia Y mayor, 90 = hacia X mayor, 270 = hacia X menor. Si la deja vacía, el programa diseña todo.
5b. **PREFERENCIAS_Y_PRESUPUESTO:** modo de diseño (A, B o C), presupuesto máximo (vacío = sin tope), tipos de rack
   permitidos, si acepta comprar (`no` obliga al modo B) y equipo de manipulación (manual o mecánico).
6. **OBSTACULOS:** columnas, muros interiores, puertas, escaleras, tableros, extintores, salidas de emergencia,
   luminarias y rociadores (para estos dos, `alto_m` = altura a la que están).
7. **ZONAS:** despacho (desde aquí se miden los recorridos en modo almacén), caja (en modo tienda), ingreso,
   recepción, etc. **PASILLOS:** ancho mínimo por uso. **EQUIPOS:** manual, transpaleta, apilador, montacargas.

**Otras vías:** un **DXF** (las capas `MUROS`, `COLUMNAS`, `PUERTAS`, `ESTANTES`, `SALIDAS`, `EXTINTORES`,
`TABLEROS`, `ESCALERAS`, `CONTORNO` se reconocen solas; si no, el asistente las asigna y usted confirma la unidad) o
una **imagen/PDF**: calibre la escala dibujando una línea de distancia conocida y trace los elementos con el mouse
(es la vía menos precisa). En ambas vías los estantes son opcionales; si los traza, llegan con niveles y capacidad
supuestos: corríjalos.

> **Plantillas antiguas:** la plantilla del local versión 2.0 (con la hoja `ESTANTES` obligatoria) se rechaza con una
> guía de migración: copie LOCAL, OBSTACULOS, ZONAS, EQUIPOS y PASILLOS a la plantilla nueva; si quiere conservar sus
> estantes, cópielos en `ESTANTES_EXISTENTES` y elija el modo B o C.

En la pantalla «Esto es lo que entendí», cada advertencia tiene un botón **Corregir** que abre la fila exacta;
al aplicar, el plano y el 3D se recalculan sin volver a subir nada.

### 3.3 Ventas (`plantilla_ventas.xlsx`)

Una fila por línea de comprobante: `fecha_hora` (día primero: `05-11-2026 10:35`), `comprobante`, `codigo_barras`,
`cantidad`, `precio_unitario`, `total` y `costo` opcional. **No es obligatorio usarla:** suba el reporte de su sistema
tal cual; el asistente propone las equivalencias de columnas, usted las corrige con listas desplegables y el
programa las recuerda para la próxima vez. Los Excel grandes se guardan en `datos_procesados/` (formato `.parquet`)
y la segunda lectura es instantánea mientras el archivo no cambie.

---

## 4. Cómo leer el panel de normativas

Las normas **ya vienen incluidas** en `normativas/normativas.json`. Cada tarjeta muestra:

- nombre y número; a qué se aplica; **la regla que produce en el modelo** (por ejemplo «peso por unidad ≤ 25 kg»);
- si es obligatoria o recomendada; la fuente oficial;
- el **estado de verificación**: `verificada` o `por verificar`, con su fecha de revisión;
- el **semáforo sobre su local**: cumple / no cumple / por verificar / no aplica, con el elemento exacto que incumple
  (por ejemplo «Estante E3 bloquea el extintor X1»).

| Norma | Estado |
|---|---|
| RM 375-2008-TR, Norma Básica de Ergonomía: 25 kg general, 15 kg con mayor protección, 40 kg personal entrenado en situaciones aisladas | **Verificada** |
| Ley 29783 y DS 005-2012-TR (mod. DS 006-2014-TR) — SST | Por verificar |
| Norma A.130 del RNE — evacuación e incendios | Por verificar |
| ITSE — inspecciones técnicas de seguridad | Por verificar |
| NTP 399.010-1 — señalización | Por verificar |
| NTP 350.043-1 — extintores | Por verificar |
| Norma A.120 — accesibilidad (modo tienda) | Por verificar |
| Ley 29571 — exhibición de precios | Por verificar |
| RM 132-2015/MINSA (farmacias) y vigilancia sanitaria DIGESA (alimentos) | Por verificar; se activan según el rubro |

**Los valores «por verificar» (anchos de pasillo, despejes, distancia a rociadores, alturas) son valores iniciales
prudentes, no citas del texto legal.** Para confirmarlos:

1. Busque la norma por su número en el diario oficial El Peruano (`busquedas.elperuano.pe`) o en el portal del
   ministerio (gob.pe/vivienda para el RNE, gob.pe/inacal para las NTP, gob.pe/indecopi, gob.pe/minsa).
2. Verifique que sea el **texto vigente** (con sus modificaciones).
3. Compare el valor con el de `normativas/normativas.json`; si difiere, corríjalo allí.
4. Cambie `"estado": "por verificar"` por `"verificada"` y ponga la fecha en `"fecha_revision"`.

En el panel puede **ajustar un valor** (por ejemplo 15 kg en vez de 25 kg) o **desactivar una norma** que no aplique
a su rubro: el programa lo advierte, lo registra en el acta y lo muestra en el reporte final. La pestaña **Reglas de
negocio** (lo pesado abajo, frágil no debajo de lo pesado, FEFO, productos para niños abajo, alto valor en zona
controlada, stock mínimo) y la **matriz de incompatibilidades** entre categorías son editables.

---

## 5. Los tres modos de diseño y el catálogo de racks

- **A. Diseñar desde cero (por defecto):** no hay estantes que conservar; el programa propone tipos, cantidad,
  medidas y ubicación de los racks.
- **B. Reutilizar mis estantes existentes:** solo se usan los estantes declarados (no se compra nada). Si no cabe
  todo, dice qué queda fuera y cuánto espacio falta.
- **C. Mixto:** los estantes existentes quedan **fijos** y se agregan módulos nuevos dentro del presupuesto.

**Catálogo de racks** (`configuracion/catalogo_racks.json`, editable en el Paso 5 → «Catálogo de racks»): góndola de
tienda, estante metálico ligero (ángulo ranurado), rack selectivo para pallets, estante de oficina o archivo y
cantiléver. Cada tipo tiene medidas, niveles y su altura, capacidad por nivel, equipo necesario, **precio, montaje y
vida útil**. **Los precios iniciales son valores típicos de referencia: confirme con su proveedor.**

**Cómo editar precios:** en el Paso 5 abra «Catálogo de racks», cambie la celda (precio, montaje, medidas, marque o
desmarque «¿Permitido?» o agregue una fila) y pulse «Guardar catálogo de racks». Para el costo final (sin volver a
optimizar), edite la tabla de costeo del Paso 8: el total, la recuperación, el VAN y la TIR se recalculan al instante.

Un tipo más alto que la altura libre útil menos la holgura de techo (luminarias, rociadores) se usa con menos
niveles; uno que pide equipo mecánico no se usa si el local trabaja a mano.

## 6. El modelo, en breve

- **Módulos candidatos** (reglas geométricas, no es otro modelo): cada tipo permitido en las cuatro orientaciones,
  sobre una cuadrícula de 50 cm, en filas, perímetro e islas. **No se genera** un candidato que choca con una
  columna, tapa una puerta, una salida, un extintor o un tablero, invade una zona funcional (despacho, caja,
  cuarentena…) o deja un pasillo menor al mínimo; tampoco si su pasillo no está conectado con las salidas. Los pares
  de candidatos que se solapan o se tapan el pasillo se guardan como **conflictos**. Si hay más de 1 500, se conservan
  los mejores (cerca del despacho y con buen aprovechamiento) repartidos por todo el local, y se avisa.
- **Posición** = un tramo (≈ 0,6 m) de un nivel de un estante o módulo.
- **Variables:** `z[m]` (se instala el módulo *m*), `x[i,j]` (producto *i* en posición *j*), `y[i]` (no ubicado, con
  penalización muy alta), `u[c,e]` (categoría *c* usa el estante *e*), `s[p,e]` (par vendido junto en el mismo estante).
- **Objetivo:** almacén: minimizar Σ rotación × costo de acceso × x + λ × Σ costo anualizado × z + penalizaciones;
  tienda: maximizar Σ margen × exposición × x − λ × Σ costo anualizado × z. Costo anualizado = (precio + montaje) /
  vida útil. Con λ = 1, la inversión anualizada de la propuesta rápida pesa lo mismo que su recorrido.
- **Restricciones nuevas:** `x[i,j] ≤ z[módulo de j]`; `z[m] + z[m'] ≤ 1` si hay conflicto; presupuesto
  Σ (precio + montaje) × z ≤ tope; en los modos B y C los existentes tienen `z = 1`; en el modo B no hay candidatos.
- **Restricciones duras:** una posición por producto; ancho, volumen y peso por nivel (y por piso si se dio su
  capacidad); altura libre; límite ergonómico; incompatibilidades por distancia; alto valor, peligrosos y frío solo
  donde corresponde; el stock mínimo (días de cobertura × rotación) cabe en la posición. Si un producto necesita más
  ancho que un tramo, puede ocupar tramos contiguos del mismo nivel.
- **Blandas (penalizadas):** pesados abajo, frágiles arriba, perecibles a altura cómoda, productos para niños abajo,
  agrupar por categoría, productos del mismo comprobante en el mismo estante.
- **Escala:** se descartan pares imposibles, entran al modelo hasta 160 módulos (los de la heurística y los mejores
  alternativos), se conservan los mejores candidatos por producto, hay tiempo límite (para todo el proceso) y brecha
  configurables y una **heurística de respaldo** (elegir módulos por calidad y llenarlos por rotación) que da la
  propuesta rápida y el arranque en caliente; el programa muestra cuánto mejora el modelo frente a ella. Al final las
  distancias se vuelven a medir caminando con los racks instalados.
- **Si no cabe todo**, explica por qué y propone alternativas con su costo: ampliar el presupuesto, racks más altos,
  liberar una zona, definir una zona controlada o reducir el stock exhibido.
- **Validador independiente:** revisa la propuesta contra todas las restricciones duras con un código distinto al
  del modelo.
- **Antes:** si no registró `ubicacion_actual`, se simula con orden alfabético por categoría y con orden aleatorio
  (semilla fija).

Todos los parámetros de negocio están en `configuracion/ajustes.json` (cortes ABC, tiempo límite, ancho de tramo,
tarifa por hora, minutos por reubicación, tasa, etc.) y se pueden editar sin tocar el código.

---

## 7. La evidencia (Paso 7): ¿resuelve el problema?

Es **análisis estadístico** sobre los resultados, no otro modelo:

1. **Planteamiento:** escriba empresa, rubro, problema y objetivo; el programa agrega un **diagnóstico con cifras**
   (distancia y tiempo por pedido, % de productos A en posiciones desfavorables si hay `ubicacion_actual`,
   aprovechamiento del volumen, incumplimientos) y redacta la frase del problema.
2. **Simulación con pedidos reales:** cada comprobante, reducido a sus productos del catálogo, es un pedido (los de
   una línea cuentan igual). La ruta de cada pedido se calcula por los pasillos (caminos mínimos sobre la cuadrícula,
   una sola matriz de distancias) con el vecino más cercano desde y hacia el despacho; la distancia se convierte en
   tiempo con la velocidad de caminata y los segundos por producto (editables). Con muchos pedidos se usa una
   **muestra aleatoria reproducible** (semilla fija, 5 000 por defecto) y se avisa.
3. **Escenarios:** situación actual (o simulada), **30 réplicas aleatorias factibles**, la heurística y la propuesta.
4. **Contraste:** H₀ «la propuesta no reduce la distancia media por pedido» y H₁ «la reduce»; Shapiro–Wilk decide
   entre t de Student pareada y Wilcoxon; se informan estadístico, valor p, tamaño del efecto e IC 95 % por bootstrap.
   Con muestras grandes se advierte que casi todo sale significativo: mire el efecto y los metros.
5. **Sensibilidad de las conclusiones** (±20 % en precios, rotación, límite de peso y λ) y **validación técnica**
   (restricciones duras, totales de ventas, reproducibilidad).
6. **Veredicto** con semáforo y **umbrales editables** (reducción ≥ 15 %, p < 0,05, cero violaciones duras,
   factibilidad, cumplimiento normativo, confiabilidad ≥ 70 %, recuperación ≤ 24 meses). **No está fijado de
   antemano**: sale de los datos y dice qué falta si no se cumple. El recuadro **«Límites de la evidencia»** siempre
   está visible.

## 8. Entregables (carpeta `resultados/`)

- **Costeo editable** (Paso 8): dos escenarios lado a lado (por ejemplo «Proveedor A» y «Proveedor B»); se guarda en
  `resultados/costeo.json` y se puede reabrir.
- `informe_gerencial.docx` y `.xlsx`: 1 a 2 páginas con problema, solución, inversión, ahorro anual, recuperación,
  VAN, TIR, riesgos, cumplimiento normativo, supuestos y recomendación, con las cifras que usted editó.
- **Paquete del artículo** (`resultados/articulo/`): Tablas 1–9 en Excel y Word (estilo APA), Figuras 1–8 en PNG a
  300 ppp y HTML, `resultados_para_redactar.md` (párrafos con las cifras reales), `ficha_metodologica.md` (datos,
  parámetros, semilla y fecha para replicar), `normas_y_fuentes.md` (normas con su estado; **no se inventan
  referencias**) y `LEEME_articulo.md` (dónde va cada tabla y figura). Úselo así: lea el LEEME del paquete, copie las
  tablas y figuras en su artículo según la sección sugerida y reescriba con sus palabras los párrafos propuestos.
- Lista de compra de racks (CSV) y diseño de racks dentro de `propuesta_distribucion.xlsx`.
- `propuesta_distribucion.xlsx`: resumen, diseño de racks, lista de compra, ubicaciones, lista de reubicación,
  indicadores, evidencia, reporte normativo, calidad de datos, supuestos, acta y cambios a normas.
- **Lista de reubicación** ordenada por beneficio: la «tanda 1» concentra el 80 % del beneficio; muévala primero
  sin detener la operación.
- `visual_3d.html`: se abre con doble clic (no necesita internet ni Python). Botones de cámara (planta, frontal,
  isométrica, ojos), vista (después, antes, mapa de calor, solo estantes), filtro ABC, recorrido y deslizador por nivel.
- `acta_confirmaciones.md` / `.json`: qué se confirmó, quién y cuándo.
- `figuras_informe/`: PNG en alta resolución y `tablas_informe.xlsx`; además `informe_esqueleto.md` con las
  secciones del informe del curso y los números del caso ya colocados.

---

## 9. Rendimiento

`python pruebas/medir_rendimiento.py` mide cada operación con el caso real y falla si alguna supera su meta (el
resultado queda en `resultados/rendimiento.md`). La app muestra los tiempos de la última corrida en la barra lateral
(«⏱️ Rendimiento»). Medición en esta computadora (Windows 11, Python 3.14):

| Operación | Meta | Medido |
|---|---|---|
| Recargar la app / cambiar de paso | < 1 s | 0,3 s |
| Ventas desde caché `parquet` | < 3 s | 0,3 s |
| Primera lectura del Excel de 16 MB (motor calamine) | < 60 s | 8–9 s (openpyxl: ≈ 40 s) |
| Propuesta rápida (740 productos con ventas, 973 en catálogo) | < 5 s | 4,3–4,7 s (margen pequeño) |
| Optimización completa (límite 60 s) | ≤ límite | 59,7 s (el límite cubre todo el proceso) |
| Vista 3D (≈ 2 160 cajas) | < 3 s | 1,0 s |
| Mover/rotar el 3D | fluido | medido de forma indirecta (≈ 26 000 triángulos agrupados por color) |
| Recalcular el costeo | < 300 ms | 2–3 ms |

La primera apertura de la app tarda unos 7 s porque se importan las librerías; después, cada recarga es inmediata.

---

## 10. Preguntas frecuentes

**¿Tengo que medir mis estantes?** No. El programa diseña los racks. Solo si quiere conservar estantes que ya tiene,
declárelos en `ESTANTES_EXISTENTES` y elija el modo B o C.

**¿Los precios de los racks son reales?** No: son valores típicos de referencia y así se rotulan en pantallas, tablas
e informes. Pida cotizaciones y cámbielos en el catálogo de racks o en el costeo.

**¿Qué hace el deslizador λ?** Hacia la izquierda prioriza el ahorro de recorrido (más racks y mejor ubicados); hacia
la derecha prioriza una menor inversión (menos racks).

**El veredicto salió rojo o amarillo, ¿está mal el programa?** No necesariamente: el veredicto no está fijado de
antemano. Lea qué criterios fallan y qué datos faltan (por lo general, medidas reales de los productos A o la
ubicación actual).

**¿Puedo usarlo si no tengo las medidas de mis productos?** Sí: active «medidas estimadas». El programa lee el nombre
(`625ML`, `36G`, `425GR`, `X20`, `7 PCS`) y usa medidas típicas del rubro, siempre marcadas como *estimado*. La
confiabilidad baja; mida primero los productos de la plantilla prellenada.

**¿Por qué mis ventas «fuera del catálogo» son tantas?** Porque se trabaja solo con productos del catálogo. En el
caso de prueba, de 2 784 códigos vendidos solo 740 están en el catálogo. Revise la lista de los 50 de más soles en
el Paso 3 y agréguelos al catálogo si corresponde.

**El modelo dice «Factible (se detuvo por tiempo)».** Encontró una buena solución pero no terminó de demostrar que es
la mejor. Suba el tiempo límite en «Ajustes del modelo» o acepte la brecha mostrada.

**Algunos productos no se ubicaron.** La tabla dice por qué (demasiado alto, supera el límite de peso, alto valor sin
zona controlada, falta espacio…) y el programa sugiere cuántos módulos de estante faltan y su costo.

**¿Se guarda mi trabajo si cierro el navegador?** Los archivos de `resultados/` y el acta sí; los datos cargados en la
pantalla no. Guarde el local con «Descargar el local tal como está (Excel)» para volver a subirlo.

**¿Cómo corro las pruebas?** `python -m pytest` dentro de la carpeta `acomoda` (tarda unos 10 minutos; la prueba de
la app completa es la más larga).

---

## 11. Limitaciones conocidas

- La mejora es **estimada por simulación** con pedidos reales; no está medida en el local.
- Sin `ubicacion_actual`, el «antes» es simulado sobre los mismos racks propuestos (llenado sin método): mide el
  valor de ubicar bien los productos, no el de cambiar los racks.
- Los precios de racks, la velocidad de caminata y los segundos por producto son supuestos editables.
- Los candidatos se generan en una cuadrícula de 50 cm; durante la optimización la distancia de cada posición se
  mide sin los demás candidatos (aún no se sabe cuáles se instalan) y al final se vuelve a medir con los racks
  instalados. La conectividad se garantiza para cada candidato; una combinación rara de racks podría encerrar un
  área: el validador de rutas de evacuación del reporte normativo lo revisaría.
- El modelo usa como máximo 160 módulos y, con muchos productos, suele terminar por tiempo («Factible») con brecha.
- CBC 2.10.3 se cae con algunos modelos grandes si se combina el arranque en caliente con su preprocesamiento: el
  programa usa el arranque en caliente sin preprocesamiento y, si falla, reintenta sin él.
- Las medidas estimadas son aproximadas; el resultado solo es tan bueno como las medidas de los productos A.
- El costo de acceso usa una grilla de pasillos (25 cm) y un factor ergonómico simplificado por altura.
- El ahorro supone que el tiempo de picking es proporcional a la distancia; no modela congestión ni reposición
  desde una reserva.
- Cada producto ocupa una sola posición (o tramos contiguos de un mismo nivel).
- La vía «imagen/PDF» depende de la calibración manual; la vía DXF supone niveles y capacidades que debe corregir.
- Las normas «por verificar» deben confirmarse en el texto oficial; el programa no reemplaza la inspección ITSE ni
  la opinión de un profesional.

## 12. Datos que aún debe medir o confirmar (caso de Juliaca)

- **Precios reales de racks** (cotizaciones) y el presupuesto máximo.
- **Velocidad de caminata y segundos por producto** del personal (cronometre unos pedidos).
- **Zona controlada** junto a la caja (hoy los productos de alto valor quedan sin lugar porque no hay ninguna).

- **Medidas y peso de los productos:** el catálogo trae `VOLUMEN(m²)` y `PESO(Kg)` vacíos en el 100 % de los
  productos (además, «volumen en m²» es una unidad incorrecta). Use `plantillas_generadas/plantilla_catalogo_prellenada.xlsx`
  (ordenada por ventas reales).
- **El local real:** largo, ancho, altura libre, columnas, puertas, salidas, extintores, tableros y zonas (los
  estantes solo si los va a conservar). El local de ejemplo **no es real**.
- **Categorías** de los ~334 productos que quedaron como «SIN CATEGORÍA».
- **Ubicación actual** de los productos (opcional), para que el «antes» sea real y no simulado.

---

## 13. Estructura de carpetas

```
acomoda/
├── app.py                    aplicación Streamlit (8 pasos)
├── requirements.txt          dependencias con versión exacta
├── LEEME.md                  esta guía
├── normativas/               normas incluidas y perfiles de rubro (JSON editables)
├── configuracion/            ajustes.json (parámetros), catalogo_racks.json (tipos y precios referenciales)
│                             y mapeo_ventas.json (equivalencias recordadas)
├── modulos/                  plantillas, carga, análisis, medidas, normas, diseno_racks, modelo_optimo (el único
│                             modelo), indicadores, evidencia, costeo, articulo, 2D, 3D, reportes
├── plantillas_generadas/     plantillas descargables
├── datos_entrada/            Excel del caso de prueba
├── datos_procesados/         caché .parquet y archivos de trabajo del solver
├── resultados/               entregables
└── pruebas/                  pruebas automáticas (pytest)
```

## 14. Versión local (ejecutable)

- Acomoda funciona **solo en la computadora**, sin servidor ni internet. Ver sección 1 para el ejecutable.
- **El progreso se guarda solo** en `Acomoda_datos/datos_procesados/proyectos/` (o `datos_procesados/proyectos/` si
  se ejecuta desde el código). Al abrir de nuevo continúa el último proyecto.
- Los datos reales (`datos_entrada/`) **no se suben** al repositorio (ver `.gitignore`); los botones
  "Usar el catálogo/reporte de prueba" solo aparecen si esos archivos existen.
- El paso 7 muestra primero el recuadro **🎯 Decisión** (qué hacer, por qué, cuatro cifras y los siguientes pasos);
  el detalle estadístico queda oculto tras un interruptor. El paso 8 genera el **borrador del artículo en Word**
  (`BORRADOR_articulo.docx`) con las cifras ya escritas y los espacios por completar resaltados en amarillo.
