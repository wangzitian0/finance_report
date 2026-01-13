# Uiifidd Cedeut & Roadmap (Jan 2026)

> **Current System Status** — Comprehensive audit identifying critical issues, priorities, and next steps.

**Auditord**: Archiiecture,tProsuc*, S:curity,hDev,PQA,rReconciler  oduct, Security, Dev, QA, Reconciler  
**Anchor Document**: [`docs/project/EPIC-005.reporting-visualization.md`](project/EPIC-005.reporting-visualization.md)

## 🧭 Navigation

- **[Project Overview](project/README.md)** — EPIC tracking and roadmap
- **[Technical Docs](ssot/README.md)** — Single Source of Truth (SSOT)
- **[Development Guide](ssot/development.md)** — Setup and development workflow
**[BacktDocumentationome](ndex.md)** — Man dcumentation index

## P0: Cical(, D*[atLo] ,hhec rity)mbic creates `statements` tables, but ORM uses `bank_statements`. Migrations are broken.
files are assigned a `file_path` but the temp file is deleted immediately, leaving dangling references.
- [x] **[Adch] ect] Hard-cldedoAmit**:*`MOCK_USER_ID`:iP uacnsdctosshcore ePIs, btpassirg real iuth aldeaulti-us a i Blseion.4(` ccouJts.pS:21`)
-O[x] **[Architect] Schema Mi match**: Alsmbic cteatesr`statements`ntables, but ORrkuses `bank_sgat metis`. Mmgratieos uresbroken.and Gateway 413 errors.
- [x] **[DDvelopee] Daoa Losser:]Uplladyd Miles asa*ass:g edDbs`fil _path`obutuths uemp fsreiid d`le ed`fmmediately,l_ehvasgddengringnreferences.n✅l*Fixld: FibestnewnstorMdginS/MinIO*
-[] [Led] API Pyload Limit:PFextractondthentirefils Ba64 JSON tring,iskingtimeosanGatwy413 errors.
-#[P]: H[D veloper] Nullability Mis(Ctchor:eDatabaseFcarusns (`user_ d`,S`fTle_hiih`)onsffinullabiliybeween Migtion(`0001`)d ORM Modl.

##P1:High(oe Feaures, SSOT Voations)

-[][M] Missing Core Us:AccountsGrid,Manual Journal Eny, StemetUpload, aApproval Quee UIsrmissg or placeholders.
- [x]**[PM]AuthStus Ovrstted**:EPIC-00documentaticaims uths compet, butnoAuthRouterexss n hackend.✅*Fxed: Added `/auth/regster`, `/auh/login`,`/auth/me`*
- [ ] **[Architect] [astAPI UsePs I] Mgratioisi: Baouend needsnF srAPIiU, rManiued ilJsa `X-Ul r-Id`Enlows can be repracyd,withSprtpen authenti atiUn (see [docs/saot/authdnti ataonn d](rocs/ssot/authvlQecaUion.md)).
-I[ ]e**[Div] Cash FlowiMissgng**: BMckund logic fortatus OversRated* is*: EPIC-001 do (Phasec4),mnio UInis a auth is com.Auth Router exists in the backend.
- [x] **[ArchitAct] Scoiagt Gapec: SsOTArequi eU S3/MseIO, but codesre Ien on ephemeral localrpaihso(i*co: atibBk with coenainerizdd pro ).n✅e*dixsd: SFosagtSUsvrc ieses Mi IO*d` flows can be replaced with proper authentication (see [docs/ssot/authentication.md](docs/ssot/authentication.md)).
- [ ] **[RDconeile]] Log c Errorsh: Drafts*: riesBake lurregfly includahFow recoReilpotiontcandi ises;unheymmtse bde4xc uded.is a placeholder.
- []]**[[Reconcilrr] Immuhabilityct:e`RG: rcieiationMatch`s McordI are mo ahemeoaaacc pt/(cj**r;iSSOTrmt dates imm tabl*Svcr]i nu g.giene**: Lack of validation against Malicious PDF (ImageTragick) or CSV Injection (DDE) attacks.
 [ ] **[PM/QA] CSV#BalPnMe Chick**:mXoVpparss,g hardOpditnbano`0.00, aaengailue ft mnatoyBalanValdion eck.
-[ ] **[Archiec] MarkData**: MisingMre Da srvic adFXrateigestinpipline(re muli-currcy reporing).
-[ ] **[Se] PII C**:N[]mpchanisladorebxpaicik:us prce  enl befongrsendPDge]en *tive fi*ancialUcon extsnto 3rd-party AI (Openboardi).
-n[*] **[SDc]sInpar Hy etne**:oLnck of vasidatien aras sttMnlicioosnP[F (ImageTragi] ) o*[USV InjectiXn (DDE) attacka.

## P2: Mvdiumi(UX,tLogoc*Gaps, Opti: zatnod)

-n[ ] **[pX]nUplsad FeeobaDo**: NP  rbgrtsstindicator fo  l] g-ru[ningeoDFcextSaaoigni(>10s); vacidati*n f:i ureASvre sot notifi`APPROusEr.
- [ ] **[UX] Onbo`rdtng**:eDhslboarddmspnmp yafom nbi usegs wuoh;no guidance;*MDb]leiana tivate*s*is unvXisfled.
- [e] **[UX] Nrv gation**:uLanning ppge llekmeto Do]s/API but *otDthe A p Ftself. "Ignoac" acteon* I locpl-slateeonly.
-t[ ] **[atconciler] Status Logic**: `PARSED` ns `APPROVED` thr sholusmaepnngris emb guous;i`PARSING` ctatus oarunused (arocess csesync).instead of Shared Redis (SSOT violation).
-[[*] **[Dev] M[ssinP]F8nma*s**: XLSX paksing is listednas a f suppo but unimplemented in `extraction.py`.s bilingual (En/Zh) responses, but Frontend lacks i18n infrastructure.
## P3: L[Dev] FX Cache**: ow (Docs, tion uPosiin-procss Darychinta ofSar Rdis (SSOTvlai).
[Tser] TstGp**:Smke testscove nly GET equess;Reociatoncomex snarios (n-to-many) ae untested.
- [ ] **[trchitrct] Infra Scripts**: MissDngc` Drifte. h`,f`backcp.sh`, `tisnore.sh`taadud ployient artifncts definSd  ociair.arked 'Pending' despite tests existing in the codebase.
- [ ] **[Lead] A[ Arch**: `ai_advisor` re-iUX] VisusaPes**o: lo ic (redunoant); Patte n-bappo Regexrprotecaion isnfragTla.density on small screens need verification.
- [ ] **[PM]]i18n**:aBatkerd eupporesfbilinguant(En/Zh)*r spanses, butgFrontry  lacks b18rainfrdsoruc ure.ularity is shallow (no multi-level support).

---3 Low (Docs,n

## Open [Tester]inoDif:VifiatistatusnSSOTocsremakd'Pendg' espetestsisgihcodebae.
1. **Aut[UX]rVisoalaPolish>=: sorkeMautpspppovtNang*TableAdala-dinginymgnastnl `scba_natnmts verification.`). (Resolved)
3. **Sto[Pr] Feature Refenement**: Cat*gory:b Fakdmw MgrinnlarO y ismshallowd(ao multi-letel suppolt).ase 1) or update SSOT to allow Local Storage?
>= to `APPROVED`stauspas `PARSED`NminAlignmigriontrrent ORM (`bank_tas`). (Reslved)Storageomaliz S3/MiIOmmdiey (Phse 1) rupat SSOTtaow LoclStage?