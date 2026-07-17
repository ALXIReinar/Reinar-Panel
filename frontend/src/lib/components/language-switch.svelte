<script lang="ts">
	import LanguagesIcon from '@lucide/svelte/icons/languages';
	import { Button } from '$lib/components/ui/button/index.js';
	import * as DropdownMenu from '$lib/components/ui/dropdown-menu/index.js';

    // FIXME: пока что ниче не делает
	let language = $state('en');
</script>

<DropdownMenu.Root>
	<DropdownMenu.Trigger>
		{#snippet child({ props })}
			<Button variant="outline" size="icon" {...props}>
				<LanguagesIcon />
			</Button>
		{/snippet}
	</DropdownMenu.Trigger>
	<DropdownMenu.Content>
		<DropdownMenu.Group>
			<DropdownMenu.RadioGroup bind:value={language}>
				<DropdownMenu.RadioItem value="en">English</DropdownMenu.RadioItem>
				<DropdownMenu.RadioItem value="ru">Русский</DropdownMenu.RadioItem>
			</DropdownMenu.RadioGroup>
		</DropdownMenu.Group>
	</DropdownMenu.Content>
</DropdownMenu.Root>
