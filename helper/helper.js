// Ayudante de CS2 Stats para hablar con Steam. Lo maneja la app de Python por stdin/stdout (una línea JSON por mensaje).
//
// Qué hace:
//  * Inicio de sesión con QR (o usuario y contraseña que escribe el usuario) usando la librería oficial de login de Steam.
//  * Con la cuenta secundaria: se conecta al Game Coordinator de CS2 y, por cada código de partida, pide la URL de la demo.
//  * También con la cuenta secundaria: le manda a tu cuenta principal el resumen de la partida por el chat de Steam.
// Nunca toca el juego ni su memoria. No guarda contraseñas: la app solo guarda el token de sesión que devuelve Steam.

const readline = require('readline');
const SteamUser = require('steam-user');
const GlobalOffensive = require('globaloffensive');
const { LoginSession, EAuthTokenPlatformType, EAuthSessionGuardType } = require('steam-session');

function send(event, data = {}) {
	process.stdout.write(JSON.stringify({ event, ...data }) + '\n');
}

let session = null;

function platformOf(name) {
	return name === 'web' ? EAuthTokenPlatformType.WebBrowser : EAuthTokenPlatformType.SteamClient;
}

function watchSession(platform, wantCookies) {
	session.on('authenticated', async () => {
		let result = { refreshToken: session.refreshToken, accountName: session.accountName, steamId: session.steamID.getSteamID64() };
		if (platform === 'web' || wantCookies) {
			try {
				result.cookies = await session.getWebCookies();
			} catch (err) {
				send('error', { message: 'No se pudieron obtener las cookies de Steam: ' + err.message });
				return;
			}
		}
		send('authenticated', result);
	});
	session.on('timeout', () => send('error', { code: 'timeout', message: 'Se venció el tiempo para iniciar sesión. Probá de nuevo.' }));
	session.on('error', (err) => send('error', { message: err.message }));
	session.on('remoteInteraction', () => send('scanned'));
}

async function qrLogin(cmd) {
	session = new LoginSession(platformOf(cmd.platform));
	session.loginTimeout = 180000;
	watchSession(cmd.platform, cmd.cookies);
	let start = await session.startWithQR();
	send('qr', { url: start.qrChallengeUrl });
}

async function credLogin(cmd) {
	session = new LoginSession(platformOf(cmd.platform));
	session.loginTimeout = 180000;
	watchSession(cmd.platform, cmd.cookies);
	let start = await session.startWithCredentials({ accountName: cmd.accountName, password: cmd.password });
	if (start.actionRequired) {
		let kinds = start.validActions.map((a) => a.type);
		if (kinds.includes(EAuthSessionGuardType.DeviceConfirmation)) {
			send('guard', { kind: 'confirm' });
		} else if (kinds.includes(EAuthSessionGuardType.DeviceCode)) {
			send('guard', { kind: 'device' });
		} else if (kinds.includes(EAuthSessionGuardType.EmailCode)) {
			send('guard', { kind: 'email' });
		}
	}
}

async function guardCode(cmd) {
	if (!session) {
		throw new Error('No hay un inicio de sesión en curso.');
	}
	await session.submitSteamGuardCode(cmd.code);
}

function withTimeout(promise, ms, message) {
	return Promise.race([promise, new Promise((_, reject) => setTimeout(() => reject(new Error(message)), ms))]);
}

async function fetchGames(cmd) {
	const client = new SteamUser({ autoRelogin: false });
	const csgo = new GlobalOffensive(client);
	client.on('refreshToken', (token) => send('refreshToken', { refreshToken: token }));

	await withTimeout(new Promise((resolve, reject) => {
		client.once('loggedOn', resolve);
		client.once('error', reject);
		client.logOn({ refreshToken: cmd.refreshToken });
	}), 30000, 'Steam no respondió al iniciar sesión.');
	send('status', { message: 'Conectado a Steam' });

	try {
		await withTimeout(client.requestFreeLicense([730]), 20000, 'timeout licencia');
	} catch (err) {
		// Si ya tiene CS2, Steam puede no responder: no es un problema.
	}
	client.gamesPlayed([730]);
	await withTimeout(new Promise((resolve) => {
		if (csgo.haveGCSession) {
			resolve();
		} else {
			csgo.once('connectedToGC', resolve);
		}
	}), 45000, 'El Game Coordinator de CS2 no respondió.');
	send('status', { message: 'Conectado al Game Coordinator de CS2' });

	for (const code of cmd.sharecodes) {
		try {
			const list = await withTimeout(new Promise((resolve) => {
				csgo.once('matchList', (matches) => resolve(matches));
				csgo.requestGame(code);
			}), 15000, 'sin respuesta');
			const match = list && list[0];
			if (!match || !match.roundstatsall || !match.roundstatsall.length) {
				send('game', { sharecode: code, ok: false, message: 'Steam no tiene datos de esa partida (puede tener más de 30 días).' });
				continue;
			}
			const last = match.roundstatsall[match.roundstatsall.length - 1];
			send('game', {
				sharecode: code, ok: true,
				matchId: String(match.matchid), matchTime: match.matchtime,
				demoUrl: last.map || '', teamScores: last.team_scores || [],
				reservationId: String(last.reservationid || ''),
			});
		} catch (err) {
			send('game', { sharecode: code, ok: false, message: err.message });
		}
		await new Promise((r) => setTimeout(r, 1500)); // sin apurar al Game Coordinator
	}
	client.gamesPlayed([]);
	client.logOff();
	send('done');
}

async function sendMessage(cmd) {
	// La cuenta secundaria le escribe a tu cuenta principal, como un amigo. Tienen que ser amigos en Steam:
	// si tu cuenta ya le mandó la solicitud, la acepta; si no, se la manda (las cuentas limitadas no pueden).
	const client = new SteamUser({ autoRelogin: false });
	client.on('refreshToken', (token) => send('refreshToken', { refreshToken: token }));
	const friendsReady = new Promise((resolve) => client.once('friendsList', resolve));
	await withTimeout(new Promise((resolve, reject) => {
		client.once('loggedOn', resolve);
		client.once('error', reject);
		client.logOn({ refreshToken: cmd.refreshToken });
	}), 30000, 'Steam no respondió al iniciar sesión.');
	try {
		await withTimeout(friendsReady, 10000, 'sin lista de amigos');
	} catch (err) {
		// Sin lista de amigos se intenta igual.
	}
	const R = SteamUser.EFriendRelationship;
	let relation = client.myFriends[cmd.to];
	if (relation === R.RequestRecipient) {
		await client.addFriend(cmd.to);
		relation = R.Friend;
	}
	if (relation !== R.Friend) {
		let reason = 'not_friends';
		if (relation !== R.RequestInitiator) {
			try {
				await client.addFriend(cmd.to);
				reason = 'request_sent';
			} catch (err) {
				reason = 'limited';
			}
		}
		client.logOff();
		send('done', { sent: false, reason });
		return;
	}
	client.setPersona(SteamUser.EPersonaState.Online);
	await withTimeout(client.chat.sendFriendMessage(cmd.to, cmd.text), 15000, 'Steam no confirmó el mensaje.');
	await new Promise((r) => setTimeout(r, 1500));
	client.logOff();
	send('done', { sent: true });
}

const handlers = { qr_login: qrLogin, cred_login: credLogin, guard_code: guardCode, fetch_games: fetchGames,
	send_message: sendMessage };

readline.createInterface({ input: process.stdin }).on('line', async (line) => {
	let cmd;
	try {
		cmd = JSON.parse(line);
	} catch (err) {
		return;
	}
	if (cmd.cmd === 'quit') {
		process.exit(0);
	}
	const handler = handlers[cmd.cmd];
	if (!handler) {
		send('error', { message: 'Comando desconocido: ' + cmd.cmd });
		return;
	}
	try {
		await handler(cmd);
	} catch (err) {
		send('error', { message: err.message, eresult: err.eresult });
	}
});

send('ready');
