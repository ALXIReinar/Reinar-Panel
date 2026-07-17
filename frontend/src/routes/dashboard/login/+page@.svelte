<script lang="ts">
	import Input from '$lib/components/ui/input/input.svelte';
	import { Button } from '$lib/components/ui/button';
	import { Login } from '$lib/api/auth';
	import { goto } from '$app/navigation';
	import { ModeWatcher } from 'mode-watcher';

	let login = $state('');
	let password = $state('');
    let error = $state('');

	const submit = async () => {
        error = "";
        let success = await Login(login, password);
        if (success) {
            console.log("Успешно вошел");
            goto('/dashboard');
        } else {
            console.log("Ошибка входа");
            error = "Ошибка входа";
        }
	};
</script>

<ModeWatcher />
<div class="flex items-center justify-center h-screen">
	<div class="flex flex-col items-center gap-5 w-1/4">
		<h1 class="text-4xl">Login</h1>
		<h1 class="text-2xl text-muted">ReinarPanel</h1>
		<!-- <InputGroup.Root> -->
		<!-- 	<InputGroup.Addon> -->
		<!-- 		<SearchIcon /> -->
		<!-- 	</InputGroup.Addon> -->
		<!-- 	<InputGroup.Input placeholder="Search..." /> -->
		<!-- </InputGroup.Root> -->
		<Input bind:value={login} type="email" placeholder="Login" />
		<Input bind:value={password} type="password" placeholder="Password" />
		<Button onclick={submit}>Login</Button>
        <p class='text-destructive'>{error}</p>
	</div>
</div>
