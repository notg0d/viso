#ifndef PayloadRoot
  #error PayloadRoot must be supplied by scripts/build-installer.ps1
#endif
#ifndef VisoVersion
  #error VisoVersion must be supplied by scripts/build-installer.ps1
#endif
#ifndef OutputRoot
  #error OutputRoot must be supplied by scripts/build-installer.ps1
#endif
#define DeployHash GetSHA256OfFile(PayloadRoot + "\installer\deploy.ps1")
#define CommonHash GetSHA256OfFile(PayloadRoot + "\installer\signin-common.ps1")
#define ManifestHash GetSHA256OfFile(PayloadRoot + "\installer\payload.json")

[Setup]
AppId={{6E91E7AA-7344-4509-8DCC-1E41A5821A0D}
AppName=Viso
AppVersion={#VisoVersion}
AppPublisher=Viso contributors
AppPublisherURL=https://github.com/notg0d/viso
AppSupportURL=https://github.com/notg0d/viso/issues
DefaultDirName={autopf}\Viso
UsePreviousAppDir=no
DisableDirPage=yes
DisableProgramGroupPage=yes
DefaultGroupName=Viso
PrivilegesRequired=admin
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0
OutputDir={#OutputRoot}
OutputBaseFilename=Viso-{#VisoVersion}-Setup-x64
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
DisableWelcomePage=no
InfoBeforeFile=setup-info.txt
UninstallDisplayIcon={app}\Viso.exe
CloseApplications=no
RestartApplications=no
RedirectionGuard=yes
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
; The trusted helper owns protected staging, verification, the directory swap,
; rollback and payload removal. Inno owns shortcuts and its uninstall registration.
Source: "{#PayloadRoot}\*"; DestDir: "{tmp}\payload"; Flags: dontcopy recursesubdirs

[Icons]
Name: "{commonprograms}\Viso"; Filename: "{app}\Viso.exe"; WorkingDir: "{app}"
Name: "{commondesktop}\Viso"; Filename: "{app}\Viso.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\Viso.exe"; Description: "Open Viso to enroll and link your Windows account"; Flags: nowait postinstall skipifsilent runasoriginaluser

[UninstallDelete]
Type: dirifempty; Name: "{app}"

[Code]
var
  ConsentPage: TInputOptionWizardPage;
  PayloadDirectory, TransactionDirectory, ResultPath: String;
  DeploymentReady, InstallationComplete, RemovalNeedsRestart: Boolean;
  KeepLinks: Boolean;

function Quoted(const Value: String): String;
begin
  Result := '"' + Value + '"';
end;

function RunDeployment(const Action: String): Boolean;
var
  HelperDirectory, Parameters: String;
  ExitCode: Integer;
begin
  if (Action = 'Uninstall') or (Action = 'CheckUninstall') then
    HelperDirectory := ExpandConstant('{app}\installer')
  else
    HelperDirectory := PayloadDirectory + '\installer';
  if (GetSHA256OfFile(HelperDirectory + '\deploy.ps1') <> '{#DeployHash}') or
     (GetSHA256OfFile(HelperDirectory + '\signin-common.ps1') <> '{#CommonHash}') then
    RaiseException('Installer deployment helpers failed integrity verification.');
  DeleteFile(ResultPath);
  Parameters := '-NoProfile -NonInteractive -ExecutionPolicy Bypass -File ' +
    Quoted(HelperDirectory + '\deploy.ps1') + ' -Action ' + Action +
    ' -ExpectedManifestHash {#ManifestHash} -ResultFile ' + Quoted(ResultPath);
  if (Action = 'Install') or (Action = 'ValidatePayload') then
    Parameters := Parameters + ' -Payload ' + Quoted(PayloadDirectory);
  if (Action <> 'Uninstall') and (Action <> 'CheckUninstall') and (Action <> 'ValidatePayload') then
    Parameters := Parameters + ' -Transaction ' + Quoted(TransactionDirectory);
  if (Action = 'Uninstall') and KeepLinks then
    Parameters := Parameters + ' -KeepAccountLinks';
  Result := Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Parameters, '', SW_HIDE, ewWaitUntilTerminated, ExitCode);
  Result := Result and (ExitCode = 0) and
    (GetIniString('Result', 'Success', '0', ResultPath) = '1');
end;

function InitializeSetup: Boolean;
var
  VerificationResult: Boolean;
  Receipt: String;
begin
  Result := True;
  if ExpandConstant('{param:VERIFYONLY|0}') = '1' then begin
    // Integrity-only extraction: no directories/services/registration installed.
    ExtractTemporaryFiles('{tmp}\payload\*');
    PayloadDirectory := ExpandConstant('{tmp}\payload');
    ResultPath := ExpandConstant('{tmp}\viso-verify-result.ini');
    VerificationResult := RunDeployment('ValidatePayload');
    Receipt := ExpandConstant('{param:VERIFYRESULTFILE|}');
    if Receipt <> '' then
      if not FileCopy(ResultPath, Receipt, False) then
        RaiseException('Could not save the verification receipt.');
    if VerificationResult then
      Log('Viso embedded payload verification passed. No installation performed.')
    else
      Log('Viso embedded payload verification failed. No installation performed.');
    Result := False; // Intentional cancellation after verification, exit code 1.
  end;
end;

procedure InitializeWizard;
begin
  ConsentPage := CreateInputOptionPage(wpInfoBefore, 'Windows face sign-in',
    'Everything is included. Account enrollment is still yours to authorize.',
    'Setup will install the desktop, bundled runtime/models, and Windows sign-in components. ' +
    'Existing account links and enrollment are retained. Password/PIN providers are not changed.', False, False);
  ConsentPage.Add('I understand face sign-in is experimental and have working Windows password/PIN access.');
  ConsentPage.Values[0] := False;
  WizardForm.FinishedLabel.Caption := 'Viso desktop and Windows sign-in are installed. ' +
    'Open Viso as your ordinary signed-in Windows user, enroll your face, then link that account in Settings. ' +
    'Existing links need no relink unless your password, profile or camera changed.';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = ConsentPage.ID then begin
    if WizardSilent then
      Result := ExpandConstant('{param:ACCEPTSIGNINRISK|0}') = '1'
    else
      Result := ConsentPage.Values[0];
    if not Result then
      SuppressibleMsgBox('Confirm that you understand the sign-in risks and have ordinary password/PIN access. ' +
        'Silent installation requires /ACCEPTSIGNINRISK=1.', mbError, MB_OK, IDOK);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if DeploymentReady then Exit;
  // Defense in depth: skipped wizard pages cannot bypass sign-in consent.
  if WizardSilent then begin
    if ExpandConstant('{param:ACCEPTSIGNINRISK|0}') <> '1' then begin
      Result := 'Silent installation requires /ACCEPTSIGNINRISK=1.';
      Exit;
    end;
  end else if not ConsentPage.Values[0] then begin
    Result := 'Explicit experimental sign-in consent is required.';
    Exit;
  end;
  if CompareText(ExpandConstant('{app}'), ExpandConstant('{autopf}\Viso')) <> 0 then begin
    Result := 'Windows sign-in must be installed to Program Files\Viso. Do not override /DIR.';
    Exit;
  end;
  ExtractTemporaryFiles('{tmp}\payload\*');
  PayloadDirectory := ExpandConstant('{tmp}\payload');
  TransactionDirectory := ExpandConstant('{autopf}\Viso.setup-') + ExtractFileName(ExpandConstant('{tmp}'));
  ResultPath := ExpandConstant('{tmp}\viso-deploy-result.ini');
  if RunDeployment('Install') then
    DeploymentReady := True
  else begin
    Result := GetIniString('Result', 'Message', 'Viso installation failed. See the Setup log.', ResultPath);
    // An error can request a manual restart in its message, never an automatic
    // prerequisite reboot (including /VERYSILENT without /NORESTART).
    NeedsRestart := False;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and DeploymentReady then begin
    InstallationComplete := True;
    if not RunDeployment('Commit') then
      SuppressibleMsgBox('Viso is installed, but old protected backup cleanup did not complete. ' +
        'See the Setup log and recovery guide before removing any backup files.', mbInformation, MB_OK, IDOK);
  end;
end;

procedure DeinitializeSetup;
begin
  if DeploymentReady and not InstallationComplete then
    if not RunDeployment('Rollback') then
      SuppressibleMsgBox('Setup did not complete and automatic recovery failed. ' +
        'Use ordinary Windows password/PIN access and consult the recovery guide.', mbError, MB_OK, IDOK);
end;

function InitializeUninstall: Boolean;
begin
  KeepLinks := ExpandConstant('{param:KEEPACCOUNTLINKS|0}') = '1';
  if not UninstallSilent then
    KeepLinks := SuppressibleMsgBox('Keep encrypted Windows account links for a later reinstall?' + #13#10 +
      'Choose No to delete the stored account-password snapshots. Your personal desktop enrollment is retained either way.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES;
  ResultPath := ExpandConstant('{tmp}\viso-uninstall-result.ini');
  Result := RunDeployment('CheckUninstall');
  if not Result then
    SuppressibleMsgBox(GetIniString('Result', 'Message', 'Viso removal failed. Close Viso and retry.', ResultPath),
      mbError, MB_OK, IDOK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then begin
    if not RunDeployment('Uninstall') then
      RaiseException(GetIniString('Result', 'Message', 'Viso removal failed. Restart and retry uninstall.', ResultPath));
    RemovalNeedsRestart := GetIniString('Result', 'RestartRequired', '0', ResultPath) = '1';
  end;
end;

function UninstallNeedRestart: Boolean;
begin
  // Interactive removal may offer a restart; silent removal never restarts.
  if RemovalNeedsRestart then Log('Viso removal requires a manual restart.');
  Result := RemovalNeedsRestart and not UninstallSilent;
end;
