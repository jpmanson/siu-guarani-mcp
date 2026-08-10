# TODO

Pendientes detectados en el desarrollo de `siu-guarani-mcp`.

## Escritura (requieren decisión explícita)

Todas las herramientas actuales son **read-only** (GET). El portal expone
formularios POST que todavía no tocamos. Exponer cualquiera de estas
implica escribir sobre datos institucionales, así que hay que decidir
caso por caso, con confirmación explícita y validaciones fuertes.

- [ ] **Carga de asistencia** — POST a `asistencias/<hash>/<clase_id>`
      con campos `alumnos[<hash>][PRESENTE]`.
- [ ] **Carga de temas dictados** — POST a `temas_dictados/<hash>/<clase_id>`
      con campos `clase`, `tema_planificado`, `tema_dictado`.
- [ ] **Carga de notas de cursada (promoción)** — POST a
      `cursada/guardar/<hash>/<n>`, campos
      `renglones[<id>][fecha_promocion]`, `[nota_promocion]`,
      `[resultado_promocion]`, `[observacion_promocion]`.
- [ ] **Carga de notas de mesa de examen** — POST a
      `notas_mesa_examen/guardar/<hash>/<n>`, campos
      `renglones[<id>][instancia]`, `[escala_nota]`, `[fecha]`, `[nota]`, `[resultado]`.

### Consideraciones para cuando se implemente escritura
- [ ] Designar las tools como `*_cargar` / `*_guardar` (no `_docente` genérico).
- [ ] Pedir confirmación explícita antes de cada tarea de escritura (no auto-ejecutar).
- [ ] Validar y sanitizar todos los inputs; nunca pasar datos crudos.
- [ ] Registrar siempre qué se modificó (log/auditoría) sin volcar PII a logs.
- [ ] Distinguir claramente write vs read en la documentación del README.

## Mejoras de lectura

Completadas:
- [x] `detalle_cursada(url)` — parseo específico y tipado de las clases de una cursada (por categoría).
- [x] `detalle_mesa(url)` — parseo específico de los datos de una mesa.
- [x] `inscriptos_examen(url)` — inscriptos a mesa de examen con salida minimizada de PII.
- [x] `reporte_actas` con filtro por origen/período/actividad.

Pendientes:
- [ ] Export a XLSX de actas/inscriptos, no solo de cursos.
- [ ] Paginación robusta en `reporte_actas` si el listado crece.

## Calidad / infra

- [ ] Confirmar que el badge de CI aparece una vez publicado el workflow.
- [ ] Considerar adherencia estricta al Agent Plugins v1.0.0 (validación de esquemas en CI ya incluida).
