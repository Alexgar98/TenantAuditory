# TenantAuditory

Lamentablemente no me ha dado tiempo a terminar el código así que no hay una cosa que yo sepa que funcione. Lo siento, al menos no tenéis que usar vuestro escaso tiempo en probarlo ¯\\_(ツ)_/¯ (?)

La herramienta debería poder conectarse al tenant, ya sea pidiendo las credenciales o usando directamente las que se nos ha proporcionado. Una vez dentro, se debería hacer una llamada a la API de Microsoft Graph para obtener la información necesaria.

Para evitar muchas llamadas a API, intentaría descargar directamente, si fuera posible, toda la información que se necesita y guardarla en una base de datos SQLite (así, en lugar de llamar a la API cada vez que se necesite información, solo se llama una vez; el resto se hace en local como consultas a bases de datos); esta operación debería hacerse cada vez que se inicie la aplicación para que descargue los datos más actualizados posible. Desde esa base de datos se podría organizar la información, ya sea desde herramientas como Jupyter Notebook (que es lo que he querido hacer) o convirtiendo los datos a CSV para que sean fácilmente accesibles desde Excel. Entiendo que en un entorno real podría ser mejor trabajar desde Cloud en lugar de descargarse los datos, pero para esta prueba debería ser suficiente y no creo que haya tantos datos que descargar (¿verdad?).

Con los datos ya ordenados, se podría hacer un script que envíe un correo a aquellos usuarios que no tengan activada la autenticación MFA para que la activen o se les borra la cuenta por seguridad, y también a aquellos usuarios que estén inactivos más de X tiempo para que vuelvan a loguearse o se les borra la cuenta.
