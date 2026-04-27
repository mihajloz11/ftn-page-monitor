# FTN page update monitor

Mali monitor za stranicu:

https://www.elektronika.ftn.uns.ac.rs/digitalni-sistemi-otporni-na-greske/specifikacija/specifikacija-predmeta/

Skript skine stranicu, očisti HTML u običan tekst, uporedi hash sa prethodnim pokretanjem i prikaže Windows notifikaciju ako se tekst promenio. Mejl je podržan, ali je podrazumevano isključen.

## 1. Podešavanje

Kopiraj primer konfiguracije:

```powershell
Copy-Item config.example.json config.json
```

Otvori `config.json`. Za Windows notifikacije ne moraš ništa dodatno da podešavaš.

Ako kasnije želiš i mejl, promeni `"email": { "enabled": false }` u `true` i popuni SMTP podatke. Za Gmail ne koristiš običnu lozinku naloga, nego **App password**:

1. Uključi 2-Step Verification na Google nalogu.
2. Napravi App password za Mail.
3. Tu vrednost upiši u `smtp_password`.

Ako koristiš drugi mejl servis, promeni `smtp_host`, `smtp_port`, `smtp_username` i `smtp_password`.

## 2. Prvo pokretanje

```powershell
.\run-monitor.ps1
```

Prvo pokretanje samo snima trenutno stanje i ne šalje mejl. Svako sledeće pokretanje šalje mejl ako vidi promenu.

Za probnu notifikaciju bez čekanja promene:

```powershell
.\run-monitor.ps1 -TestNotification
```

## 3. Automatsko pokretanje na Windowsu

Otvori PowerShell u ovom folderu i pokreni:

```powershell
$workdir = (Get-Location).Path
$runner = (Resolve-Path .\run-monitor.ps1).Path
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$runner`"" -WorkingDirectory $workdir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "FTN site update monitor" -Action $action -Trigger $trigger -Description "Proverava FTN stranicu i salje mejl ako se promeni."
```

Provera ručno:

```powershell
Start-ScheduledTask -TaskName "FTN site update monitor"
```

Brisanje taska:

```powershell
Unregister-ScheduledTask -TaskName "FTN site update monitor" -Confirm:$false
```

## 4. Cloud provera preko GitHub Actions

Ako zelis da provera radi i kad ti racunar nije ukljucen, koristi `.github/workflows/ftn-page-monitor.yml`.

Najjednostavnije obavestenje je preko ntfy:

1. Instaliraj ntfy aplikaciju ili otvori https://ntfy.sh u browseru.
2. Izmisli dugacak privatni naziv topic-a, npr. `ftn-dsog-nekidugacaknasumicantekst`.
3. Pretplati se na taj topic u ntfy aplikaciji.
4. Na GitHub repo-u dodaj secret `NTFY_TOPIC` sa tom vrednoscu.
5. Pushuj ovaj folder na GitHub.

Workflow se pokrece na svakih 30 minuta i mozes ga rucno pokrenuti kroz GitHub Actions tab.
