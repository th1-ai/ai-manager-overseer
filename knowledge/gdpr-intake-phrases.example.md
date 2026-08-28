# GDPR intake phrases

<!--
Copy this to knowledge/gdpr-intake-phrases.md to change what
tools/gdpr.py:classify_intake() treats as a GDPR-shaped email. Keep the
three headings - they are the only kinds config/agent.yaml: gdpr.checklists
knows how to work (see docs/how-it-works.md design decision 16). One phrase
per line; matching is a case- and accent-folded substring check against the
subject + body (`tools/gdpr.py:_fold()`), so "l'effacement" and "leffacement"
both match, and so does typing it with or without the accent on either side.

A UK/EU property gets requests in whatever language its guests write in, not
just English (Finding 4, 2026-08-27 simulation) - this file ships phrases for
English plus the five languages this template family's own fixtures and
docs assume a European hotel sees most (es/fr/de/it/pt). If your guests
write in others too, add a block the same way: one `## <kind>` section per
request type, one phrase per line, any language, any order. Nothing here
calls a model - see the module docstring for why that is deliberate for a
statutory process.
-->

## erasure

- delete my data
- delete my personal data
- right to be forgotten
- erase my information
- remove my details
- forget me
<!-- es -->
- eliminar mis datos
- borrar mis datos personales
- derecho al olvido
- derecho de supresion
- eliminar mi informacion
- olvidame
<!-- fr -->
- supprimer mes donnees
- supprimer mes donnees personnelles
- droit a l'effacement
- droit a l'oubli
- effacer mes informations
- oubliez-moi
<!-- de -->
- meine daten loschen
- meine personenbezogenen daten loschen
- recht auf vergessenwerden
- recht auf loschung
- meine informationen loschen
- vergiss mich
<!-- it -->
- cancellare i miei dati
- cancellare i miei dati personali
- diritto all'oblio
- diritto alla cancellazione
- cancellare le mie informazioni
- dimenticami
<!-- pt -->
- apagar os meus dados
- eliminar meus dados pessoais
- direito ao esquecimento
- direito de apagamento
- apagar minhas informacoes
- esqueca-me

## access

- copy of my data
- copy of all data
- subject access request
- what data do you hold
- send me my information
- what information do you have on me
<!-- es -->
- copia de mis datos
- solicitud de acceso
- que datos tienen de mi
- envienme mi informacion
- que informacion tienen sobre mi
<!-- fr -->
- copie de mes donnees
- demande d'acces
- quelles donnees detenez-vous
- envoyez-moi mes informations
- quelles informations avez-vous sur moi
<!-- de -->
- kopie meiner daten
- auskunftsantrag
- welche daten haben sie uber mich
- senden sie mir meine informationen
- welche informationen haben sie uber mich
<!-- it -->
- copia dei miei dati
- richiesta di accesso
- quali dati avete su di me
- inviatemi le mie informazioni
- quali informazioni avete su di me
<!-- pt -->
- copia dos meus dados
- pedido de acesso
- que dados tem sobre mim
- enviem-me minhas informacoes
- que informacoes tem sobre mim

## rectification

- correct my details
- my name is misspelled
- fix my information
- update my personal details
- wrong information on my invoice
<!-- es -->
- corregir mis datos
- mi nombre esta mal escrito
- corregir mi informacion
- actualizar mis datos personales
- informacion incorrecta en mi factura
<!-- fr -->
- corriger mes coordonnees
- mon nom est mal orthographie
- corriger mes informations
- mettre a jour mes donnees personnelles
- informations erronees sur ma facture
<!-- de -->
- meine daten korrigieren
- mein name ist falsch geschrieben
- meine informationen korrigieren
- meine personlichen daten aktualisieren
- falsche informationen auf meiner rechnung
<!-- it -->
- correggere i miei dati
- il mio nome e scritto male
- correggere le mie informazioni
- aggiornare i miei dati personali
- informazioni errate sulla mia fattura
<!-- pt -->
- corrigir os meus dados
- meu nome esta errado
- corrigir minhas informacoes
- atualizar meus dados pessoais
- informacao incorreta na minha fatura
