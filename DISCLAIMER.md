# Disclaimer e Condizioni di Utilizzo

*jot* è un'applicazione desktop open source distribuita gratuitamente sotto licenza MIT. Questo documento fornisce informazioni sui limiti di responsabilità, sul funzionamento dell'applicazione e sull'uso dei servizi terzi integrati.

---

### 1. Architettura Locale e Servizi di Terze Parti (BYOK)
- **Nessun Backend Proprietario**: L'applicazione viene eseguita sul computer dell'utente e non utilizza server proxy, backend o database gestiti dallo sviluppatore. I file e le bozze vengono conservati localmente; i contenuti necessari all'elaborazione AI vengono trasmessi direttamente a Google Gemini.
- **Comunicazione Diretta con Google Gemini**: L'applicazione adotta il modello *Bring Your Own Key* (BYOK). L'utente configura la propria API key e il proprio progetto Google. Le richieste per l'elaborazione AI vengono trasmesse direttamente e cifrate (TLS) tra la macchina dell'utente e gli endpoint ufficiali di Google (`generativelanguage.googleapis.com`).
- **Termini e Policy di Terze Parti**: L'utilizzo delle API Gemini (incluse quote per progetto/modello, disponibilità dei modelli, requisiti regionali, fatturazione e trattamento dei dati) è soggetto ai [Termini di Servizio di Google](https://policies.google.com/terms), ai [Termini delle Google APIs](https://developers.google.com/terms) e ai [Termini Aggiuntivi di Gemini API / AI Studio](https://ai.google.dev/gemini-api/terms) applicabili all'account e al progetto dell'utente. I limiti RPD/RPM sono stabiliti a livello di progetto Google Cloud e non si moltiplicano con l'uso di più chiavi appartenenti al medesimo progetto.
- **Requisiti di Età**: L'accesso e l'impiego delle API Gemini tramite l'applicazione sono soggetti ai requisiti di età previsti dai termini Google applicabili.


---

### 2. Diritto d'Autore e Registrazioni
L'utente è l'unico responsabile di verificare preventivamente di avere il diritto di registrare, elaborare, conservare e utilizzare le lezioni e i relativi materiali didattici, nel rispetto delle normative vigenti e dei regolamenti del proprio ateneo o istituto. L'utente non deve diffondere, pubblicare o condividere materiale protetto senza le necessarie autorizzazioni.

---

### 3. Dati Personali e Sanitari
Le registrazioni audio e video possono contenere dati personali o, nel caso di lezioni in ambito medico-sanitario, dati relativi alla salute, rientranti tra le categorie particolari di dati personali previste dall'art. 9 GDPR. L'utente è tenuto a verificare di essere legittimato a trattare tali dati per la specifica finalità e deve astenersi dall'inviare a servizi cloud esterni contenuti che non sia autorizzato a trasmettere, adottando le opportune cautele di anonimizzazione preventiva.

---

### 4. Natura Assistiva dell'Output AI
La trascrizione e la sintesi sono generate automaticamente da modelli di intelligenza artificiale che possono commettere inesattezze, omissioni o allucinazioni. Il testo prodotto costituisce una bozza di supporto allo studio personale e non sostituisce l'ascolto critico, i libri di testo o l'insegnamento dei docenti. L'utente è tenuto a verificare e revisionare sempre il contenuto finale.

---

### 5. Esclusione di Garanzie e Limitazione di Responsabilità
Il software viene fornito a titolo gratuito "così com'è" (*AS IS*), senza garanzie di alcun tipo, esplicite o implicite. Lo sviluppatore non potrà essere ritenuto responsabile per qualsiasi danno diretto o indiretto, perdita di dati, sanzioni o controversie derivanti dall'utilizzo dell'applicazione, dalla violazione di diritti di terzi o dall'interazione con servizi cloud esterni.

---

### 6. Fonti e Documentazione di Riferimento
- [Gemini API – Termini Aggiuntivi di Servizio](https://ai.google.dev/gemini-api/terms)
- [Google APIs Terms of Service](https://developers.google.com/terms)
- [Google Terms of Service](https://policies.google.com/terms)
- [Regolamento (UE) 2016/679 – GDPR (EUR-Lex)](https://eur-lex.europa.eu/eli/reg/2016/679/oj)
- [Legge 22 aprile 1941, n. 633 sul diritto d'autore (Normattiva)](https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:legge:1941-04-22;633)
